"""Shared helper for generating friendly, sequential ticket numbers.

Ticket.id is a UUID (primary key); ticket_number is a separate, human-friendly
sequential integer surfaced in the UI/notifications. SQLite/most RDBMS only
auto-increment a single-column integer primary key, so we compute the next
value in application code instead.
"""
from sqlalchemy.orm import Session
from app.models import Ticket


def next_ticket_number(db: Session) -> int:
    max_number = db.query(Ticket.ticket_number).order_by(Ticket.ticket_number.desc()).first()
    return (max_number[0] + 1) if max_number and max_number[0] else 1000
