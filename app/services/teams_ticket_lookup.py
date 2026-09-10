from sqlalchemy.orm import Session

from app.models import Ticket


def get_ticket(ticket_id: int, db: Session):
    return (
        db.query(Ticket)
        .filter(Ticket.id == ticket_id)
        .first()
    )


def get_recent_user_tickets(
    email: str,
    db: Session,
    limit: int = 5,
):
    return (
        db.query(Ticket)
        .filter(Ticket.contact_email == email)
        .order_by(Ticket.updated_at.desc())
        .limit(limit)
        .all()
    )
