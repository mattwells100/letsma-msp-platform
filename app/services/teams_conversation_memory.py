"""Database-backed conversational memory for the Teams bot."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    insert,
    select,
    update,
)
from sqlalchemy.orm import Session


metadata = MetaData()

teams_conversation_states = Table(
    "teams_conversation_states",
    metadata,
    Column("conversation_id", String(512), primary_key=True),
    Column("ticket_number", Integer, nullable=False),
    Column(
        "updated_at",
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    ),
)


def _ensure_table(db: Session) -> None:
    """Create the conversation state table if it does not exist."""
    metadata.create_all(
        bind=db.get_bind(),
        tables=[teams_conversation_states],
        checkfirst=True,
    )


def remember_ticket_number(
    db: Session,
    conversation_id: Optional[str],
    ticket_number: Optional[int],
) -> None:
    """Remember the most recently referenced ticket."""
    if not conversation_id or ticket_number is None:
        return

    _ensure_table(db)

    existing = db.execute(
        select(
            teams_conversation_states.c.conversation_id
        ).where(
            teams_conversation_states.c.conversation_id
            == conversation_id
        )
    ).first()

    now = datetime.utcnow()

    if existing:
        db.execute(
            update(teams_conversation_states)
            .where(
                teams_conversation_states.c.conversation_id
                == conversation_id
            )
            .values(
                ticket_number=int(ticket_number),
                updated_at=now,
            )
        )
    else:
        db.execute(
            insert(teams_conversation_states).values(
                conversation_id=conversation_id,
                ticket_number=int(ticket_number),
                updated_at=now,
            )
        )

    db.commit()


def get_remembered_ticket_number(
    db: Session,
    conversation_id: Optional[str],
) -> Optional[int]:
    """Return the last ticket referenced in a Teams conversation."""
    if not conversation_id:
        return None

    _ensure_table(db)

    row = db.execute(
ect(
            teams_conversation_states.c.ticket_number
        ).where(
            teams_conversation_states.c.conversation_id
            == conversation_id
        )
    ).first()

    if not row:
        return None

    return int(row[0])
