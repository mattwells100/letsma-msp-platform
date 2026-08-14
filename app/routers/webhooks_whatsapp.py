from fastapi import APIRouter, Request, Query, HTTPException, Response
from sqlalchemy.orm import Session
from fastapi import Depends

from app.database import get_db
from app.services import whatsapp_service

router = APIRouter(prefix="/webhooks/whatsapp", tags=["Webhooks - WhatsApp"])


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
    tickets = whatsapp_service.handle_inbound_payload(db, payload)
    return {"ok": True, "tickets_touched": [t.id for t in tickets]}
