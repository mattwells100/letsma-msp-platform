import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import TicketPriority, TicketStatus
from app.services.teams_customer_resolution_service import (
    CustomerResolution,
    CustomerResolutionStatus,
)
from app.services.teams_ticket_state import TeamsTicketDraft, TicketDraftState
from app.services.teams_ticket_state_service import teams_ticket_state_service
from app.services.teams_ticket_workflow_service import (
    collect_customer,
    create_ticket,
)


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, value):
        self.added.append(value)

    def commit(self):
        return None

    def refresh(self, value):
        value.status = TicketStatus.NEW


class TeamsTicketWorkflowTests(unittest.TestCase):
    def tearDown(self):
        teams_ticket_state_service.clear("conversation-1")

    def test_collect_customer_moves_draft_to_contact_collection(self):
        draft = TeamsTicketDraft("conversation-1", "user-1")
        resolution = CustomerResolution(
            status=CustomerResolutionStatus.MATCHED,
            query="Acme",
            customer_id="customer-1",
            customer_name="Acme Ltd",
        )

        with patch(
            "app.services.teams_ticket_workflow_service.resolve_customer",
            return_value=resolution,
        ):
            result = collect_customer(FakeSession(), draft, "Acme")

        self.assertEqual(result.status, "matched")
        self.assertEqual(draft.state, TicketDraftState.COLLECTING_CONTACT)
        self.assertEqual(draft.customer_id, "customer-1")

    def test_create_ticket_persists_customer_contact_and_teams_metadata(self):
        draft = TeamsTicketDraft("conversation-1", "user-1")
        draft.customer_id = "customer-1"
        draft.contact_id = "contact-1"
        draft.subject = "VPN unavailable"
        draft.description = "The office VPN is unavailable."
        draft.priority = "High"

        session = FakeSession()
        with patch(
            "app.services.teams_ticket_workflow_service.next_ticket_number",
            return_value=1200,
        ):
            result = create_ticket(
                session,
                draft,
                reporter_name="Teams user",
                service_url="https://teams.example",
            )

        ticket = session.added[0]
        self.assertIs(result.ticket, ticket)
        self.assertEqual(ticket.ticket_number, 1200)
        self.assertEqual(ticket.customer_id, "customer-1")
        self.assertEqual(ticket.contact_id, "contact-1")
        self.assertEqual(ticket.source.value, "Teams")
        self.assertEqual(ticket.priority, TicketPriority.HIGH)
        self.assertEqual(ticket.external_ref, "https://teams.example")
        self.assertEqual(draft.state, TicketDraftState.COMPLETED)

    def test_create_ticket_rejects_incomplete_draft(self):
        with self.assertRaises(ValueError):
            create_ticket(
                FakeSession(),
                TeamsTicketDraft("conversation-1", "user-1"),
                reporter_name="Teams user",
            )

    def test_create_ticket_allows_unassigned_teams_ticket(self):
        draft = TeamsTicketDraft("conversation-1", "user-1")
        draft.subject = "VPN unavailable"
        draft.description = "The office VPN is unavailable."

        session = FakeSession()
        with patch(
            "app.services.teams_ticket_workflow_service.next_ticket_number",
            return_value=1201,
        ):
            result = create_ticket(
                session,
                draft,
                reporter_name="Teams user",
            )

        self.assertEqual(result.ticket.ticket_number, 1201)
        self.assertIsNone(result.ticket.customer_id)


if __name__ == "__main__":
    unittest.main()