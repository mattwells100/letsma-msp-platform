"""
Shared helper for generating friendly, sequential ticket numbers.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Ticket


def next_ticket_number(db: Session) -> int:
    current_max = db.query(func.max(Ticket.ticket_number)).scalar()
    return (current_max or 999) + 1
