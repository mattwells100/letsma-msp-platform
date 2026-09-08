from fastapi import APIRouter, Request, HTTPException, Header, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import teams_service

router = APIRouter(prefix="/webhooks/teams", tags=["Webhooks - Teams"])


@router.post("")
async def receive(request: Request, authorization: str = Header(default=""), db: Session = Depends(get_db)):
    raw_body = await request.body()

    if not teams_service.verify_hmac_signature(raw_body, authorization):
        raise HTTPException(401, "Invalid HMAC signature from Teams outgoing webhook")

    activity = await request.json()
    ticket = teams_service.parse_inbound_activity(db, activity)

    if ticket:
        if ticket.customer:
            reply_text = (
                f"✅ Ticket #{ticket.ticket_number} logged "
                f"for {ticket.customer.name}."
            )
        else:
            reply_text = (
                f"✅ Ticket #{ticket.ticket_number} logged "
                f"(customer could not be matched)."
            )
    else:
        reply_text = "❌ Ticket creation failed."

    # Teams outgoing webhooks expect a synchronous Activity-shaped reply
    return {"type": "message", "text": reply_text}
