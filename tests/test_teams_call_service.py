from datetime import datetime, timedelta
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CallInteraction, Contact, Customer
from app.services.teams_call_service import (
    _call_records_url,
    _graph_error_detail,
    match_contact_by_phone,
    normalize_phone_number,
    process_call_record,
)
import httpx


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


class TeamsCallServiceTests(unittest.TestCase):
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