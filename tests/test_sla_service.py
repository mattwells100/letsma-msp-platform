import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.models import TicketComment, TicketStatus
from app.services.sla_service import check_sla_breaches


class FakeQuery:
    def __init__(self, items):
        self.items = items

    def filter(self, *args):
        return self

    def all(self):
        return self.items


class FakeSession:
    def __init__(self, tickets):
        self.tickets = tickets
        self.added = []
        self.commits = 0

    def query(self, model):
        return FakeQuery(self.tickets)

    def add(self, value):
        self.added.append(value)
        if isinstance(value, TicketComment):
            ticket = next(ticket for ticket in self.tickets if ticket.id == value.ticket_id)
            ticket.comments.append(value)

    def commit(self):
        self.commits += 1


class SlaServiceTests(unittest.IsolatedAsyncioTestCase):
    def _overdue_ticket(self):
        return SimpleNamespace(
            id="ticket-1",
            ticket_number=42,
            status=TicketStatus.IN_PROGRESS,
            sla_due_at=datetime.utcnow() - timedelta(minutes=5),
            comments=[],
        )

    async def test_alerts_once_and_records_internal_marker(self):
        ticket = self._overdue_ticket()
        session = FakeSession([ticket])

        with patch(
            "app.services.sla_service.teams_service.notify_sla_breach",
            new=AsyncMock(),
        ) as notify:
            first = await check_sla_breaches(session)
            second = await check_sla_breaches(session)

        self.assertEqual(first, [42])
        self.assertEqual(second, [])
        notify.assert_awaited_once_with(ticket)
        self.assertEqual(session.commits, 1)
        self.assertTrue(ticket.comments[0].is_internal_note)

    async def test_no_alert_when_no_eligible_tickets(self):
        session = FakeSession([])

        with patch(
            "app.services.sla_service.teams_service.notify_sla_breach",
            new=AsyncMock(),
        ) as notify:
            alerted = await check_sla_breaches(session)

        self.assertEqual(alerted, [])
        notify.assert_not_awaited()
        self.assertEqual(session.commits, 0)


if __name__ == "__main__":
    unittest.main()
