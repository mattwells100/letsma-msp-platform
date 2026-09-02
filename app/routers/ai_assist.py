"""
app/routers/ai_assist.py

AI-assisted helpdesk features, starting with drafting suggested ticket
replies via Azure OpenAI. Deliberately kept as a SEPARATE router from
tickets.py so this addition can't risk breaking anything already
working there.

IMPORTANT: this endpoint only ever RETURNS a suggested draft string - it
never creates a TicketComment, never sends anything to a customer, and
never modifies the ticket in any way. A technician must explicitly copy
the draft into a reply and submit it themselves via the existing
ticket-comment endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services import azure_openai_service

router = APIRouter(prefix="/api/ai-assist", tags=["AI Assist"])


@router.post("/tickets/{ticket_id}/draft-reply")
async def draft_ticket_reply(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    customer = db.query(models.Customer).get(ticket.customer_id)
    customer_name = customer.name if customer else "Unknown customer"

    comments = (
        db.query(models.TicketComment)
        .filter_by(ticket_id=ticket_id)
        .order_by(models.TicketComment.created_at.asc())
        .all()
    )
    comments_data = [
        {"author": c.author, "message": c.message, "is_internal_note": c.is_internal_note}
        for c in comments
    ]

    try:
        draft = await azure_openai_service.draft_ticket_reply(
            ticket_subject=ticket.subject,
            ticket_description=ticket.description,
            customer_name=customer_name,
            comments=comments_data,
        )
    except RuntimeError as e:
        # Azure OpenAI not configured yet - a clear, actionable message rather than a raw 500
        raise HTTPException(503, str(e))
    except Exception as e:
        raise HTTPException(502, f"Azure OpenAI request failed: {e}")

    return {"ticket_id": ticket_id, "draft_reply": draft}
