from pathlib import Path

router_file = Path("app/routers/teams_bot.py")

router_file.write_text(
'''from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ticket, TicketSource
from app.services.ticket_numbering import next_ticket_number

router = APIRouter(
    prefix="/api/teams",
    tags=["Teams Bot"]
)


@router.post("/messages")
async def receive_message(
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.json()

    text = payload.get("text", "").strip()

    if not text:
        return {
            "type": "message",
            "text": "Please enter a ticket description."
        }

    ticket = Ticket(
        ticket_number=next_ticket_number(db),
        subject=text[:100],
        description=text,
        source=TicketSource.TEAMS,
    )

    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return {
        "type": "message",
        "text": f"✅ Ticket #{ticket.ticket_number} created"
    }
''',
encoding="utf-8"
)

print("[OK] Created app/routers/teams_bot.py")
