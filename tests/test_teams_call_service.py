from datetime import datetime, timedelta
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CallInteraction, Contact, Customer, Ticket, TicketSource
from app.services.teams_call_service import (
    _call_records_url,
    _direct_routing_calls_url,
    _graph_error_detail,
    _normalise_call_record,
    assign_call_interaction,
    match_contact_by_phone,
    normalize_phone_number,
    process_call_record,
    settings,
)
import httpx


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class TeamsCallServiceTests(unittest.TestCase):
    def setUp(self):
        self._auto_tickets_enabled = settings.TEAMS_CALLS_AUTO_TICKETS_ENABLED
        self._missed_calls_enabled = settings.TEAMS_CALLS_TICKET_MISSED_CALLS_ENABLED
        self._min_duration_seconds = settings.TEAMS_CALLS_TICKET_MIN_DURATION_SECONDS

    def tearDown(self):
        settings.TEAMS_CALLS_AUTO_TICKETS_ENABLED = self._auto_tickets_enabled
        settings.TEAMS_CALLS_TICKET_MISSED_CALLS_ENABLED = self._missed_calls_enabled
        settings.TEAMS_CALLS_TICKET_MIN_DURATION_SECONDS = self._min_duration_seconds

    def test_graph_error_detail_includes_entra_error_description(self):
        response = httpx.Response(
            400,
            json={
                "error": "invalid_client",
                "error_description": "AADSTS7000215: Invalid client secret provided.",
            },
        )

        self.assertIn("invalid_client", _graph_error_detail(response))
        self.assertIn("AADSTS7000215", _graph_error_detail(response))

    def test_call_records_url_omits_unsupported_top_query_option(self):
        url = _call_records_url(datetime(2026, 9, 25, 9, 30, 0))

        self.assertIn("$filter=startDateTime ge 2026-09-25T09:30:00Z", url)
        self.assertNotIn("$top", url)

    def test_direct_routing_calls_url_uses_function_parameters(self):
        url = _direct_routing_calls_url(
            datetime(2026, 9, 25, 8, 0, 0),
            datetime(2026, 9, 25, 9, 0, 0),
        )

        self.assertIn("getDirectRoutingCalls", url)
        self.assertIn("fromDateTime=2026-09-25T08:00:00Z", url)
        self.assertIn("toDateTime=2026-09-25T09:00:00Z", url)

    def test_normalize_phone_number_strips_uk_formats(self):
        self.assertEqual(normalize_phone_number("+44 20 1234 5678"), "442012345678")
        self.assertEqual(normalize_phone_number("02012345678"), "442012345678")
        self.assertEqual(normalize_phone_number("442012345678"), "442012345678")

    def test_match_contact_by_phone_checks_contact_and_customer_numbers(self):
        db = _session()
        customer = Customer(name="ABC Solicitors", phone="020 1111 2222")
        contact = Contact(customer=customer, name="John Smith", mobile_phone="+44 20 1234 5678")
        db.add(customer)
        db.add(contact)
        db.commit()

        contact_match = match_contact_by_phone(db, "02012345678")
        self.assertEqual(contact_match.customer.id, customer.id)
        self.assertEqual(contact_match.contact.id, contact.id)

        customer_match = match_contact_by_phone(db, "+442011112222")
        self.assertEqual(customer_match.customer.id, customer.id)
        self.assertIsNone(customer_match.contact)

    def test_process_call_record_stores_unknown_and_prevents_duplicates(self):
        db = _session()
        started = datetime.utcnow() - timedelta(minutes=5)
        ended = datetime.utcnow()
        record = {
            "id": "teams-call-1",
            "startDateTime": started.isoformat() + "Z",
            "endDateTime": ended.isoformat() + "Z",
            "caller": {"identity": {"phone": {"id": "+44 7700 900123"}}},
        }

        first = process_call_record(db, record)
        second = process_call_record(db, record)

        self.assertEqual(first.id, second.id)
        self.assertEqual(db.query(CallInteraction).count(), 1)
        self.assertIsNone(first.customer_id)
        self.assertIsNone(first.contact_id)
        self.assertEqual(first.phone_number, "447700900123")
        self.assertIs(first.answered, True)

    def test_process_direct_routing_row_matches_outbound_callee(self):
        db = _session()
        customer = Customer(name="ABC Solicitors")
        contact = Contact(customer=customer, name="John Smith", mobile_phone="+44 20 1234 5678")
        db.add(customer)
        db.add(contact)
        db.commit()
        row = {
            "id": "direct-row-1",
            "callerNumber": "+44 333 000 0000",
            "calleeNumber": "02012345678",
            "startDateTime": "2026-09-25T08:35:00Z",
            "duration": 42,
        }

        normalised = _normalise_call_record(row)
        interaction = process_call_record(db, row)

        self.assertEqual(normalised["callId"], "direct-routing:direct-row-1")
        self.assertEqual(interaction.contact_id, contact.id)
        self.assertEqual(interaction.customer_id, customer.id)
        self.assertEqual(interaction.direction, "outbound")
        self.assertEqual(interaction.duration_seconds, 42)

    def test_assign_call_interaction_links_customer_and_contact(self):
        db = _session()
        customer = Customer(name="ABC Solicitors")
        contact = Contact(customer=customer, name="John Smith")
        interaction = CallInteraction(teams_call_id="teams-call-assign", direction="unknown")
        db.add(customer)
        db.add(contact)
        db.add(interaction)
        db.commit()

        assigned = assign_call_interaction(db, interaction.id, customer.id, contact.id)

        self.assertEqual(assigned.customer_id, customer.id)
        self.assertEqual(assigned.contact_id, contact.id)

    def test_assign_call_interaction_rejects_contact_from_other_customer(self):
        db = _session()
        customer = Customer(name="ABC Solicitors")
        other_customer = Customer(name="Other Ltd")
        other_contact = Contact(customer=other_customer, name="Other Person")
        interaction = CallInteraction(teams_call_id="teams-call-bad-contact", direction="unknown")
        db.add(customer)
        db.add(other_customer)
        db.add(other_contact)
        db.add(interaction)
        db.commit()

        with self.assertRaises(ValueError):
            assign_call_interaction(db, interaction.id, customer.id, other_contact.id)

    def test_process_call_record_creates_single_ticket_for_missed_call_when_enabled(self):
        settings.TEAMS_CALLS_AUTO_TICKETS_ENABLED = True
        settings.TEAMS_CALLS_TICKET_MISSED_CALLS_ENABLED = True
        settings.TEAMS_CALLS_TICKET_MIN_DURATION_SECONDS = 0
        db = _session()
        record = {
            "id": "teams-call-missed",
            "startDateTime": "2026-09-25T09:00:00Z",
            "caller": {"identity": {"phone": {"id": "+44 7700 900123"}}},
        }

        first = process_call_record(db, record)
        second = process_call_record(db, record)

        self.assertEqual(first.id, second.id)
        self.assertEqual(db.query(Ticket).count(), 1)
        self.assertEqual(first.ticket_id, db.query(Ticket).first().id)
        self.assertEqual(db.query(Ticket).first().source, TicketSource.PHONE)

    def test_process_call_record_creates_ticket_for_long_call_threshold(self):
        settings.TEAMS_CALLS_AUTO_TICKETS_ENABLED = True
        settings.TEAMS_CALLS_TICKET_MISSED_CALLS_ENABLED = False
        settings.TEAMS_CALLS_TICKET_MIN_DURATION_SECONDS = 60
        db = _session()
        record = {
            "id": "teams-call-long",
            "startDateTime": "2026-09-25T09:00:00Z",
            "endDateTime": "2026-09-25T09:02:00Z",
            "caller": {"identity": {"phone": {"id": "+44 7700 900123"}}},
        }

        interaction = process_call_record(db, record)
        ticket = db.query(Ticket).first()

        self.assertIsNotNone(ticket)
        self.assertEqual(interaction.ticket_id, ticket.id)
        self.assertIn("Long", ticket.subject)