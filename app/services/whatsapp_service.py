"""
WhatsApp Business Cloud API (Meta) integration.

Handles:
  - Webhook verification (GET) required by Meta when you register the callback URL.
  - Inbound message parsing (POST) -> auto-creates/updates a helpdesk ticket.
    * Recognised numbers  -> ticket attached to the matched customer/contact.
    * Unrecognised numbers -> UNASSIGNED ticket (customer_id = NULL) so nothing
      is ever silently dropped; a technician can assign the customer later.
  - Outbound message sending:
    * send_whatsapp_message()  -> free-form text (valid only inside the 24h
      customer-service window, e.g. an auto-confirmation right after the
      customer messages in, or a technician reply while the window is open).
    * send_whatsapp_template() -> approved template (use OUTSIDE the 24h window
      for business-initiated notifications).

handle_inbound_payload() returns a list of (Ticket, is_new) tuples so callers
can send a confirmation ONLY for tickets that were freshly created.

Setup:
  1. Create a Meta App -> add "WhatsApp" product -> https://developers.facebook.com/apps
  2. Under WhatsApp > Configuration, set the Callback URL to:
       {BASE_URL}/webhooks/whatsapp
     and the Verify Token to match WHATSAPP_VERIFY_TOKEN in .env.
  3. Subscribe to the "messages" webhook field.
  4. Generate a permanent access token (System User) and phone number ID,
     store them in WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID.

NOTE: Requires Ticket.customer_id to be NULLABLE (unassigned tickets for
unknown senders).
"""
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Customer, Contact, Ticket, TicketSource, TicketStatus, WhatsAppMessage
from app.services.ticket_numbering import next_ticket_number

GRAPH_WA_BASE = "https://graph.facebook.com/v19.0"

# Ticket statuses considered "still open" for threading subsequent inbound
# messages onto an existing ticket.
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
    """Best-effort normalisation to bare E.164 digits (no '+', spaces or dashes)."""
    if not raw:
        return raw
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("0"):
        digits = "44" + digits[1:]
    return digits


def _find_customer_by_number(db: Session, wa_number: str) -> tuple[Optional[Customer], Optional[Contact]]:
    """Match a sender to a Contact (preferred) or Customer, tolerant of formatting."""
    target = _normalise_number(wa_number)

    contact = db.query(Contact).filter(Contact.whatsapp_number == wa_number).first()
    if contact:
        return contact.customer, contact
    customer = db.query(Customer).filter(Customer.whatsapp_number == wa_number).first()
    if customer:
        return customer, None

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
            Ticket.deleted_at.is_(None),
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
        and ticket.deleted_at is None
        and ticket.source == TicketSource.WHATSAPP
        and ticket.status in _OPEN_STATUSES
    ):
        return ticket
    return None


def recipient_for_ticket(db: Session, ticket: Ticket) -> Optional[str]:
    """Resolve the best WhatsApp number to reply to for a given ticket.

    Order of preference:
      1. contact.whatsapp_number
      2. customer.whatsapp_number
      3. the most recent inbound WhatsAppMessage.from_number logged for this ticket
         (this is what makes replies to UNKNOWN senders work).
    """
    if ticket.contact and getattr(ticket.contact, "whatsapp_number", None):
        return ticket.contact.whatsapp_number
    if ticket.customer and getattr(ticket.customer, "whatsapp_number", None):
        return ticket.customer.whatsapp_number
    last_inbound = (
        db.query(WhatsAppMessage)
        .filter(
            WhatsAppMessage.ticket_id == ticket.id,
            WhatsAppMessage.direction == "inbound",
        )
        .order_by(WhatsAppMessage.id.desc())
        .first()
    )
    return last_inbound.from_number if last_inbound else None


def handle_inbound_payload(db: Session, payload: dict) -> list[tuple[Ticket, bool]]:
    """Parses a WhatsApp Cloud API webhook payload and creates/updates tickets.

    Returns a list of (Ticket, is_new) tuples. `is_new` is True only when the
    ticket was freshly created by this message (so callers can send a one-time
    confirmation). Delivery receipts (the 'statuses' array) are ignored.
    """
    results: list[tuple[Ticket, bool]] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            contacts_meta = {c["wa_id"]: c.get("profile", {}).get("name") for c in value.get("contacts", [])}

            for msg in messages:
                from_number = msg.get("from")
                wa_message_id = msg.get("id")

                # --- Idempotency guard: skip messages we've already logged ---
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

                log = WhatsAppMessage(
                    customer_id=customer.id if customer else None,
                    wa_message_id=wa_message_id,
                    from_number=from_number,
                    direction="inbound",
                    body=body,
                )
                db.add(log)

                if customer:
                    open_ticket = _find_open_ticket_for_known(db, customer)
                else:
                    open_ticket = _find_open_ticket_for_unknown(db, from_number)

                is_new = False
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
                    is_new = True

                db.flush()
                log.ticket_id = ticket.id
                db.commit()
                db.refresh(ticket)
                results.append((ticket, is_new))

    return results


async def send_whatsapp_message(to_number: str, message: str) -> dict:
    """Sends a free-form text message. Valid only within the 24h customer-service
    window (i.e. the customer messaged us in the last 24h). Outside that window
    use send_whatsapp_template()."""
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


async def send_whatsapp_template(
    to_number: str,
    template_name: str,
    language: str = "en_GB",
    body_params: Optional[list[str]] = None,
) -> dict:
    """Sends an APPROVED template message. Use this for business-initiated
    notifications OUTSIDE the 24h window (e.g. ticket status updates hours later)."""
    components = []
    if body_params:
        components = [{
            "type": "body",
            "parameters": [{"type": "text", "text": p} for p in body_params],
        }]
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
            **({"components": components} if components else {}),
        },
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GRAPH_WA_BASE}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def send_ticket_reply(db: Session, ticket: Ticket, message: str, author: str = "Letsma") -> Optional[dict]:
    """Send a technician's reply from the helpdesk out over WhatsApp, and log it.

    Works for both known customers and unknown senders (falls back to the last
    inbound number on the ticket). Returns the Graph response, or None if there
    was no number to reply to.

    NOTE: free-form only succeeds inside the 24h window. If the window has
    closed, the Graph call will raise; callers should catch and fall back to a
    template if needed.
    """
    to_number = recipient_for_ticket(db, ticket)
    if not to_number:
        return None
    result = await send_whatsapp_message(to_number, message)
    db.add(WhatsAppMessage(
        customer_id=ticket.customer_id,
        ticket_id=ticket.id,
        from_number=to_number,
        direction="outbound",
        body=message,
    ))
    # Log the reply on the ticket timeline too.
    from app.models import TicketComment
    db.add(TicketComment(
        ticket_id=ticket.id,
        author=author,
        message=message,
    ))
    ticket.updated_at = datetime.utcnow()
    db.commit()
    return result


async def notify_ticket_update(db: Session, ticket: Ticket, message: str):
    """Convenience helper to notify a customer's WhatsApp number about a ticket update."""
    if not ticket.customer_id:
        return None
    to_number = recipient_for_ticket(db, ticket)
    if not to_number:
        return None
    result = await send_whatsapp_message(to_number, message)
    db.add(WhatsAppMessage(
        customer_id=ticket.customer_id,
        ticket_id=ticket.id,
        from_number=to_number,
        direction="outbound",
        body=message,
    ))
    db.commit()
    return result
