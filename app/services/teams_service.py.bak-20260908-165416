"""
Microsoft Teams integration.

Two directions are supported:

1. OUTBOUND (notifications): post Adaptive Cards / messages into a Teams
   channel via an Incoming Webhook connector whenever a ticket is created,
   updated, or an endpoint alert fires.

2. INBOUND (ticket logging from Teams): receive messages posted to a Teams
   channel via an "Outgoing Webhook" (channel bot) and auto-create tickets
   from them, e.g. a technician or client posts "New ticket: printer down
   at Reception" in a monitored channel.

Setup - Outbound:
  1. In the target Teams channel: ... > Connectors > Incoming Webhook > Configure.
  2. Copy the URL into TEAMS_INCOMING_WEBHOOK_URL.

Setup - Inbound:
  1. In the target Teams channel: ... > Connectors > Outgoing Webhook > Create.
  2. Set the callback URL to {BASE_URL}/webhooks/teams and copy the generated
     HMAC security token into TEAMS_OUTGOING_WEBHOOK_SECRET.
  3. Teams will POST an activity payload + HMAC256 signature (in the
     "Authorization" header) whenever the bot is @mentioned in the channel.

  For a richer bidirectional bot (adaptive cards, buttons, proactive 1:1
  messages) migrate this to the Bot Framework SDK registered via Azure Bot
  Service - this module keeps things dependency-light for the MVP.
"""
import base64
import hashlib
import hmac
import json

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Ticket, TeamsMessage, Customer, TicketSource
from app.services.ticket_numbering import next_ticket_number


def verify_hmac_signature(raw_body: bytes, auth_header: str) -> bool:
    if not settings.TEAMS_OUTGOING_WEBHOOK_SECRET or not auth_header:
        return False
    expected = base64.b64encode(
        hmac.new(
            base64.b64decode(settings.TEAMS_OUTGOING_WEBHOOK_SECRET),
            raw_body,
            hashlib.sha256,
        ).digest()
    ).decode()
    provided = auth_header.replace("HMAC ", "").strip()
    return hmac.compare_digest(expected, provided)


async def post_adaptive_card(title: str, facts: dict, text: str = ""):
    """Send a simple Adaptive Card to the configured Teams channel webhook."""
    if not settings.TEAMS_INCOMING_WEBHOOK_URL:
        return None

    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"},
                        {"type": "TextBlock", "text": text, "wrap": True} if text else None,
                        {
                            "type": "FactSet",
                            "facts": [{"title": k, "value": str(v)} for k, v in facts.items()],
                        },
                    ],
                },
            }
        ],
    }
    card["attachments"][0]["content"]["body"] = [b for b in card["attachments"][0]["content"]["body"] if b]

    async with httpx.AsyncClient() as client:
        resp = await client.post(settings.TEAMS_INCOMING_WEBHOOK_URL, json=card)
        return resp.status_code


async def notify_new_ticket(ticket: Ticket, customer: Customer):
    await post_adaptive_card(
        title=f"🎫 New Ticket #{ticket.ticket_number}: {ticket.subject}",
        facts={
            "Customer": customer.name,
            "Priority": ticket.priority.value if hasattr(ticket.priority, "value") else ticket.priority,
            "Source": ticket.source.value if hasattr(ticket.source, "value") else ticket.source,
            "Status": ticket.status.value if hasattr(ticket.status, "value") else ticket.status,
        },
        text=ticket.description or "",
    )


async def notify_endpoint_alert(hostname: str, customer_name: str, reason: str):
    await post_adaptive_card(
        title=f"🚨 Endpoint Alert: {hostname}",
        facts={"Customer": customer_name, "Reason": reason},
    )


def parse_inbound_activity(db: Session, activity: dict) -> Ticket | None:
    """
    Parses a Teams "outgoing webhook" activity payload.
    Expected minimal shape (simplified from Bot Framework Activity schema):
      {
        "text": "@Letsma Bot New ticket: printer down at Reception for Acme Ltd",
        "from": {"name": "Matt Wells"},
        "conversation": {"name": "IT Support"}
      }

    Convention used: message text should contain "for <Customer Name>" so we
    can route the ticket; otherwise it is logged unassigned for manual triage.
    """
    text = activity.get("text", "").strip()
    sender = activity.get("from", {}).get("name", "Teams User")
    channel = activity.get("conversation", {}).get("name", "Teams")

    customer = None
    if " for " in text.lower():
        possible_name = text.lower().split(" for ")[-1].strip()
        customer = (
            db.query(Customer)
            .filter(Customer.name.ilike(f"%{possible_name}%"))
            .first()
        )

    log = TeamsMessage(channel_or_user=channel, direction="inbound", body=text)
    db.add(log)

    ticket = None
    if customer:
        ticket = Ticket(
            ticket_number=next_ticket_number(db),
            customer_id=customer.id,
            subject=text[:80],
            description=f"Logged via Teams by {sender} in '{channel}':\n\n{text}",
            source=TicketSource.TEAMS,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)
        log.ticket_id = ticket.id

    db.commit()
    return ticket
