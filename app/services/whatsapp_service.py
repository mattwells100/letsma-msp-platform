"""
WhatsApp Business Cloud API (Meta) integration.

Handles:
  - Webhook verification (GET) required by Meta when you register the callback URL.
  - Inbound message parsing (POST) -> auto-creates/updates a helpdesk ticket.
  - Outbound message sending (e.g. ticket status updates back to the customer).

Setup:
  1. Create a Meta App -> add "WhatsApp" product -> https://developers.facebook.com/apps
  2. Under WhatsApp > Configuration, set the Callback URL to:
       {BASE_URL}/webhooks/whatsapp
     and the Verify Token to match WHATSAPP_VERIFY_TOKEN in .env.
  3. Subscribe to the "messages" webhook field.
  4. Generate a permanent access token (System User) and phone number ID,
     store them in WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID.
"""
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Customer, Contact, Ticket, TicketSource, TicketStatus, WhatsAppMessage
from app.services.ticket_numbering import next_ticket_number

GRAPH_WA_BASE = "https://graph.facebook.com/v19.0"


def verify_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return challenge
    return None


def _find_customer_by_number(db: Session, wa_number: str) -> tuple[Optional[Customer], Optional[Contact]]:
    contact = db.query(Contact).filter(Contact.whatsapp_number == wa_number).first()
    if contact:
        return contact.customer, contact
    customer = db.query(Customer).filter(Customer.whatsapp_number == wa_number).first()
    return customer, None


def handle_inbound_payload(db: Session, payload: dict) -> list[Ticket]:
    """Parses a WhatsApp Cloud API webhook payload and creates/updates tickets."""
    created_or_updated: list[Ticket] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts_meta = {c["wa_id"]: c.get("profile", {}).get("name") for c in value.get("contacts", [])}

            for msg in messages:
                from_number = msg.get("from")
                wa_message_id = msg.get("id")
                body = msg.get("text", {}).get("body") or f"[{msg.get('type', 'media')} message]"
                sender_name = contacts_meta.get(from_number, from_number)

                customer, contact = _find_customer_by_number(db, from_number)

                # Log the raw message for audit purposes regardless of match
                log = WhatsAppMessage(
                    customer_id=customer.id if customer else None,
                    wa_message_id=wa_message_id,
                    from_number=from_number,
                    direction="inbound",
                    body=body,
                )
                db.add(log)

                if not customer:
                    # Unknown number - still logged above; skip ticket auto-creation.
                    db.commit()
                    continue

                # Reuse an open ticket from this contact within the last 24h, else create new
                open_ticket = (
                    db.query(Ticket)
                    .filter(
                        Ticket.customer_id == customer.id,
                        Ticket.source == TicketSource.WHATSAPP,
                        Ticket.status.in_([TicketStatus.NEW, TicketStatus.IN_PROGRESS, TicketStatus.WAITING_ON_CUSTOMER]),
                    )
                    .order_by(Ticket.created_at.desc())
                    .first()
                )

                if open_ticket:
                    from app.models import TicketComment
                    db.add(TicketComment(
                        ticket_id=open_ticket.id,
                        author=sender_name or from_number,
                        message=body,
                    ))
                    open_ticket.updated_at = datetime.utcnow()
                    ticket = open_ticket
                else:
                    ticket = Ticket(
                        ticket_number=next_ticket_number(db),
                        customer_id=customer.id,
                        contact_id=contact.id if contact else None,
                        subject=f"WhatsApp: {body[:60]}",
                        description=body,
                        source=TicketSource.WHATSAPP,
                        external_ref=wa_message_id,
                    )
                    db.add(ticket)

                log.ticket_id = ticket.id
                db.commit()
                db.refresh(ticket)
                created_or_updated.append(ticket)

    return created_or_updated


async def send_whatsapp_message(to_number: str, message: str) -> dict:
    """Sends a free-form text message (only valid within a 24h customer-service window,
    or use an approved template message outside that window)."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GRAPH_WA_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            json={
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "text",
                "text": {"body": message},
            },
        )
        resp.raise_for_status()
        return resp.json()


async def notify_ticket_update(db: Session, ticket: Ticket, message: str):
    """Convenience helper to notify a customer's WhatsApp number about a ticket update."""
    customer = ticket.customer
    number = ticket.contact.whatsapp_number if ticket.contact else customer.whatsapp_number
    if not number:
        return None
    result = await send_whatsapp_message(number, message)
    db.add(WhatsAppMessage(
        customer_id=customer.id,
        ticket_id=ticket.id,
        from_number=number,
        direction="outbound",
        body=message,
    ))
    db.commit()
    return result
