"""
WhatsApp Business Cloud API (Meta) integration.

Handles:
  - Webhook verification (GET) required by Meta when you register the callback URL.
  - Inbound message parsing (POST) -> auto-creates/updates a helpdesk ticket.
    * Recognised numbers  -> ticket attached to the matched customer/contact.
    * Unrecognised numbers -> UNASSIGNED ticket (customer_id = NULL) so nothing
      is ever silently dropped; a technician can assign the customer later.
  - Outbound message sending (e.g. ticket status updates back to the customer).

Setup:
  1. Create a Meta App -> add "WhatsApp" product -> https://developers.facebook.com/apps
  2. Under WhatsApp > Configuration, set the Callback URL to:
       {BASE_URL}/webhooks/whatsapp
     and the Verify Token to match WHATSAPP_VERIFY_TOKEN in .env.
  3. Subscribe to the "messages" webhook field.
  4. Generate a permanent access token (System User) and phone number ID,
     store them in WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID.

NOTE: Requires Ticket.customer_id to be NULLABLE (unassigned tickets for
unknown senders). Run the migrate-ticket-nullable-customer migration first.
"""
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Customer, Contact, Ticket, TicketSource, TicketStatus, WhatsAppMessage
from app.services.ticket_numbering import next_ticket_number

GRAPH_WA_BASE = "https://graph.facebook.com/v19.0"

# Ticket statuses considered "still open" for the purpose of threading
# subsequent inbound messages onto an existing ticket.
_OPEN_STATUSES = [
    TicketStatus.NEW,
    TicketStatus.IN_PROGRESS,
    TicketStatus.WAITING_ON_CUSTOMER,
]


def verify_webhook(mode: str, token: str, challenge: str) -> Optional[str]:
    if mode == "subscribe" and token == settings.WHATSAPP_VERIFY_TOKEN:
        return challenge
    return None


def _normalise_number(raw: Optional[str]) -> Optional[str]:
    """Best-effort normalisation to bare E.164 digits (no '+', spaces or dashes).

    WhatsApp delivers numbers like '447375291017'. Stored contact/customer
    numbers may be '+44 7375...', '07375...', etc. Normalising both sides
    massively reduces 'unknown sender' misses caused by formatting alone.
    """
    if not raw:
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    # UK convenience: turn a leading national 0 into the 44 country code.
    if digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits


def _find_customer_by_number(db: Session, wa_number: str) -> tuple[Optional[Customer], Optional[Contact]]:
    """Match a sender to a Contact (preferred) or Customer, tolerant of formatting."""
    target = _normalise_number(wa_number)

    # Fast path: exact stored match.
    contact = db.query(Contact).filter(Contact.whatsapp_number == wa_number).first()
    if contact:
        return contact.customer, contact
    customer = db.query(Customer).filter(Customer.whatsapp_number == wa_number).first()
    if customer:
        return customer, None

    # Tolerant path: compare normalised forms across all records that have a number.
    for c in db.query(Contact).filter(Contact.whatsapp_number.isnot(None)).all():
        if _normalise_number(c.whatsapp_number) == target:
            return c.customer, c
    for cu in db.query(Customer).filter(Customer.whatsapp_number.isnot(None)).all():
        if _normalise_number(cu.whatsapp_number) == target:
            return cu, None

    return None, None


def _find_open_ticket_for_known(db: Session, customer: Customer) -> Optional[Ticket]:
    return (
        db.query(Ticket)
        .filter(
            Ticket.customer_id == customer.id,
            Ticket.source == TicketSource.WHATSAPP,
            Ticket.status.in_(_OPEN_STATUSES),
        )
        .order_by(Ticket.created_at.desc())
        .first()
    )


def _find_open_ticket_for_unknown(db: Session, from_number: str) -> Optional[Ticket]:
    """Thread follow-up messages from an unrecognised number onto the same
    unassigned ticket, matched via the prior WhatsAppMessage log for that number."""
    prior = (
        db.query(WhatsAppMessage)
        .filter(
            WhatsAppMessage.from_number == from_number,
            WhatsAppMessage.ticket_id.isnot(None),
        )
        .order_by(WhatsAppMessage.id.desc())
        .first()
    )
    if not prior or not prior.ticket_id:
        return None
    ticket = db.query(Ticket).get(prior.ticket_id)
    if (
        ticket
        and ticket.source == TicketSource.WHATSAPP
        and ticket.status in _OPEN_STATUSES
    ):
        return ticket
    return None


def handle_inbound_payload(db: Session, payload: dict) -> list[Ticket]:
    """Parses a WhatsApp Cloud API webhook payload and creates/updates tickets.

    Only the 'messages' array is processed. Delivery receipts arrive under a
    'statuses' array and are intentionally ignored here.
    """
    created_or_updated: list[Ticket] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts_meta = {c["wa_id"]: c.get("profile", {}).get("name") for c in value.get("contacts", [])}

            for msg in messages:
                from_number = msg.get("from")
                wa_message_id = msg.get("id")

                # --- Idempotency guard -------------------------------------
                # Meta retries webhooks on any non-2xx / slow response. Skip
                # messages we've already logged so retries can't duplicate
                # tickets/comments.
                if wa_message_id:
                    already = (
                        db.query(WhatsAppMessage)
                        .filter(WhatsAppMessage.wa_message_id == wa_message_id)
                        .first()
                    )
                    if already:
                        continue

                body = msg.get("text", {}).get("body") or f"[{msg.get('type', 'media')} message]"
                sender_name = contacts_meta.get(from_number, from_number)

                customer, contact = _find_customer_by_number(db, from_number)

                # Log the raw message for audit purposes regardless of match.
                log = WhatsAppMessage(
                    customer_id=customer.id if customer else None,
                    wa_message_id=wa_message_id,
                    from_number=from_number,
                    direction="inbound",
                    body=body,
                )
                db.add(log)

                # Find an existing open thread (known: by customer; unknown: by number).
                if customer:
                    open_ticket = _find_open_ticket_for_known(db, customer)
                else:
                    open_ticket = _find_open_ticket_for_unknown(db, from_number)

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
                    if customer:
                        subject = f"WhatsApp: {body[:60]}"
                    else:
                        # Unassigned ticket for an unrecognised number.
                        subject = f"WhatsApp (unknown {from_number}): {body[:40]}"

                    ticket = Ticket(
                        ticket_number=next_ticket_number(db),
                        customer_id=customer.id if customer else None,
                        contact_id=contact.id if contact else None,
                        subject=subject,
                        description=body,
                        source=TicketSource.WHATSAPP,
                        external_ref=wa_message_id,
                    )
                    db.add(ticket)

                # Flush so the ticket gets an id before we back-reference it.
                db.flush()
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
    if not customer:
        # Unassigned ticket (unknown sender) - no customer to notify yet.
        return None
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
