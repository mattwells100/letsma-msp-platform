"""Scheduled SLA breach detection and notification."""
from datetime import datetime

from sqlalchemy.orm import Session

from app import models
from app.services import teams_service

SLA_ALERT_MARKER = "SLA breach alert sent"


async def check_sla_breaches(db: Session, now: datetime | None = None) -> list[int]:
    """Notify once for each overdue, still-open ticket."""
    now = now or datetime.utcnow()
    open_statuses = [
        models.TicketStatus.NEW,
        models.TicketStatus.IN_PROGRESS,
        models.TicketStatus.WAITING_ON_CUSTOMER,
    ]
    tickets = (
        db.query(models.Ticket)
        .filter(
            models.Ticket.deleted_at.is_(None),
            models.Ticket.sla_due_at.is_not(None),
            models.Ticket.sla_due_at <= now,
            models.Ticket.status.in_(open_statuses),
        )
        .all()
    )

    alerted = []
    for ticket in tickets:
        if any(SLA_ALERT_MARKER in (comment.message or "") for comment in ticket.comments):
            continue
        await teams_service.notify_sla_breach(ticket)
        db.add(
            models.TicketComment(
                ticket_id=ticket.id,
                author="SLA Monitor",
                message=f"{SLA_ALERT_MARKER} for ticket #{ticket.ticket_number}.",
                is_internal_note=True,
            )
        )
        db.commit()
        alerted.append(ticket.ticket_number)
    return alerted
