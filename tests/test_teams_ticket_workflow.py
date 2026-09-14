import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.models import KnowledgeArticle, TicketPriority, TicketStatus
from app.services.knowledge_base_service import (
    list_customer_knowledge_articles,
    upsert_knowledge_article,
)
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
from app.services.teams_issue_workflow_service import collect_issue
from app.routers.teams_bot import _match_teams_sender


class FakeQuery:
    def __init__(self, items):
        self.items = items

    def filter_by(self, **kwargs):
        matches = []
        for item in self.items:
            ok = True
            for key, value in kwargs.items():
                if getattr(item, key, None) != value:
                    ok = False
                    break
            if ok:
                matches.append(item)
        return FakeQuery(matches)

    def first(self):
        return self.items[0] if self.items else None


class FakeSession:
    def __init__(self):
        self.added = []
        self.articles = []

    def add(self, value):
        self.added.append(value)
        if isinstance(value, KnowledgeArticle):
            self.articles.append(value)

    def commit(self):
        return None

    def refresh(self, value):
        value.status = TicketStatus.NEW

    def query(self, model):
        if model is KnowledgeArticle:
            return FakeQuery(self.articles)
        return FakeQuery([])


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
                reporter_email="user@example.com",
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
        self.assertEqual(ticket.reporter_email, "user@example.com")
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

    def test_collect_issue_accepts_short_nonempty_message(self):
        draft = TeamsTicketDraft("conversation-1", "user-1")

        result = collect_issue(draft, "test")

        self.assertEqual(result.status, "collected")
        self.assertEqual(draft.description, "test")

    def test_abandoned_confirmation_draft_can_start_new_issue(self):
        draft = TeamsTicketDraft("conversation-1", "user-1")
        draft.state = TicketDraftState.AWAITING_CONFIRMATION
        draft.subject = "Old issue"
        draft.description = "Old issue description"

        draft.reset()
        result = collect_issue(draft, "New VPN issue")

        self.assertEqual(result.status, "collected")
        self.assertEqual(draft.subject, "New VPN issue")

    def test_teams_sender_match_populates_contact_and_customer(self):
        draft = TeamsTicketDraft("conversation-1", "user-1")
        contact = SimpleNamespace(id="contact-1", name="Matt Wells", customer_id="customer-1")
        customer = SimpleNamespace(id="customer-1", name="Acme Ltd")

        with patch(
            "app.routers.teams_bot.resolve_teams_sender",
            return_value=(contact, customer),
        ):
            _match_teams_sender(
                FakeSession(),
                draft,
                {"from": {"name": "Matt Wells", "email": "matt@example.com"}},
                "VPN is unavailable",
            )

        self.assertEqual(draft.contact_id, "contact-1")
        self.assertEqual(draft.customer_id, "customer-1")
        self.assertEqual(draft.customer_name, "Acme Ltd")

    def test_resolved_ticket_creates_knowledge_article(self):
        ticket = SimpleNamespace(
            id="ticket-knowledge-1",
            customer_id="customer-1",
            category="Microsoft 365",
            subcategory="Teams",
            subject="Teams meeting audio issue",
            description="Teams meeting audio cut out for remote users.",
            comments=[
                SimpleNamespace(
                    author="Support",
                    message="Confirmed the issue was caused by an outdated Teams client. Updated devices and issue cleared.",
                    is_internal_note=False,
                )
            ],
            status=TicketStatus.RESOLVED,
            resolved_at=None,
        )

        article = upsert_knowledge_article(FakeSession(), ticket)

        self.assertIsInstance(article, KnowledgeArticle)
        self.assertEqual(article.customer_id, "customer-1")
        self.assertEqual(article.category, "Microsoft 365")
        self.assertEqual(article.subcategory, "Teams")
        self.assertIn("Teams", article.title)
        self.assertIn("outdated teams client", article.summary.lower())

    def test_list_customer_knowledge_articles_returns_latest_fix(self):
        session = FakeSession()
        article = KnowledgeArticle(
            id="kb-1",
            customer_id="customer-1",
            category="Microsoft 365",
            subcategory="Teams",
            title="Microsoft 365: Teams fix",
            summary="Confirmed the issue was caused by an outdated Teams client.",
            resolution="Updated devices and issue cleared.",
        )
        session.add(article)

        results = list_customer_knowledge_articles(session, "customer-1", limit=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].subcategory, "Teams")


if __name__ == "__main__":
    unittest.main()