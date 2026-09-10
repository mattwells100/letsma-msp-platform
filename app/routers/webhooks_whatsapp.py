from fastapi import APIRouter, Request, Query, HTTPException, Response
from sqlalchemy.orm import Session
from fastapi import Depends

from app.database import get_db
from app.services import whatsapp_service
import json

router = APIRouter(prefix="/webhooks/whatsapp", tags=["Webhooks - WhatsApp"])

# Message sent back automatically when a NEW ticket is created from an inbound
# WhatsApp. Safe to send free-form because the customer just messaged us, so
# the 24h customer-service window is open.
CONFIRMATION_TEMPLATE = (
    "✅ Thanks for getting in touch — we've logged your request as "
    "ticket #{number}. Our team will be in touch shortly.\n— Letsma"
)


@router.get("")
def verify(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    """Meta calls this once when you configure the webhook callback URL."""
    challenge = whatsapp_service.verify_webhook(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(403, "Verification failed")
    return Response(content=challenge, media_type="text/plain")


@router.post("")
async def receive(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    print("WHATSAPP_INBOUND " + json.dumps(payload)[:2000])
    results = await whatsapp_service.handle_inbound_payload(db, payload)

    # Send a confirmation ONLY for tickets that were newly created by this
    # payload. Applies to known customers AND unknown senders (we reply to the
    # inbound number). A failure to confirm must never break the webhook 200,
    # otherwise Meta will retry and we could double-process.
    for ticket, is_new in results:
        if not is_new:
            continue
        try:
            to_number = whatsapp_service.recipient_for_ticket(db, ticket)
            if to_number:
                await whatsapp_service.send_whatsapp_message(
                    to_number,
                    CONFIRMATION_TEMPLATE.format(number=ticket.ticket_number),
                )
        except Exception:
            # Swallow send errors (e.g. window edge cases) — inbound handling
            # already succeeded and the ticket exists.
            pass

    return {"ok": True, "tickets_touched": [t.id for t, _ in results]}
