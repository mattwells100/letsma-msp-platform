from fastapi import APIRouter, Request, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ticket, TicketSource
from app.services.ticket_numbering import next_ticket_number
import httpx

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

    
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            await client.post(
                f"http://127.0.0.1:8000/api/ai/tickets/{ticket.id}/categorise"
            )
    except Exception as exc:
        print("Teams categorisation failed:", exc)

return {
        "type": "message",
        "text": (
            f"✅ Ticket #{ticket.ticket_number} created\\n\\n"
            f"Category: {ticket.category or 'Pending'}\\n"
            f"Subcategory: {ticket.subcategory or 'Pending'}\\n"
            f"Estimate: {ticket.estimated_minutes or '-'} mins"
        )
    }
