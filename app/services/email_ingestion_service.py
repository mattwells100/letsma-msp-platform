"""
app/services/email_ingestion_service.py

Polls the helpdesk@letsma.co.uk mailbox via Microsoft Graph, turning new
inbound emails into helpdesk tickets automatically. Handles:
  - Excluding specific senders/domains from ever creating a ticket
  - Detecting forwarded emails and extracting the ORIGINAL sender's
    details (so a ticket is correctly attributed to the customer who
    actually emailed, not the staff member who forwarded it)
  - Matching against simple keyword-triggered auto-reply rules
  - Sending a confirmation email with the ticket reference number
  - De-duplicating so re-polling never creates a second ticket for the
    same email

Requires its own dedicated Entra ID app registration (kept separate from
the per-customer Graph app used for license/contact sync, since this one
needs Mail.Read/Mail.Send - see docs/EMAIL_HELPDESK_SETUP.md for the full
setup, including the required Exchange Application Access Policy that
restricts this app to ONLY the helpdesk mailbox).
"""
import re
import html
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Ticket, TicketSource, TicketPriority, Customer, Contact,
    ExcludedEmailSender, AutoReplyRule, ProcessedEmail,
)
from app.services.ticket_numbering import next_ticket_number

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
async def _get_helpdesk_app_token() -> str:
    token_url = f"https://login.microsoftonline.com/{settings.HELPDESK_GRAPH_TENANT_ID}/oauth2/v2.0/token"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.HELPDESK_GRAPH_CLIENT_ID,
                "client_secret": settings.HELPDESK_GRAPH_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Sender exclusion
# ---------------------------------------------------------------------------
def is_sender_excluded(email_address: str, db: Session) -> bool:
    """
    Checks an email address against the ExcludedEmailSender list.
    Supports exact matches ("noreply@vendor.com") and domain wildcards
    ("*@spamdomain.com"). Matching is case-insensitive.
    """
    if not email_address:
        return False
    email_lower = email_address.strip().lower()
    domain = email_lower.split("@")[-1] if "@" in email_lower else ""

    rules = db.query(ExcludedEmailSender).all()
    for rule in rules:
        pattern = rule.pattern.strip().lower()
        if pattern.startswith("*@"):
            if domain == pattern[2:]:
                return True
        elif pattern == email_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Forwarded email parsing
# ---------------------------------------------------------------------------
_FWD_SUBJECT_PREFIX_RE = re.compile(r"^\s*(fwd?|fw)\s*:\s*", re.IGNORECASE)

# Outlook-style block, e.g.:
#   From: Jane Smith <jane@client.com>
#   Sent: Tuesday, 12 August 2026 10:15
#   To: Letsma Helpdesk <helpdesk@letsma.co.uk>
#   Subject: Printer not working
_OUTLOOK_FORWARD_RE = re.compile(
    r"From:\s*(?:(?P<name>[^<\r\n]+?)\s*)?<?(?P<email>[\w.+-]+@[\w-]+\.[\w.-]+)>?\s*[\r\n]+"
    r"(?:Sent|Date):\s*(?P<sent>[^\r\n]+)[\r\n]+"
    r"To:\s*(?P<to>[^\r\n]+)[\r\n]+"
    r"(?:Cc:\s*[^\r\n]*[\r\n]+)?"
    r"Subject:\s*(?P<subject>[^\r\n]+)",
    re.IGNORECASE,
)

# Gmail-style marker, e.g.:
#   ---------- Forwarded message ---------
#   From: Jane Smith <jane@client.com>
#   Date: Tue, 12 Aug 2026 10:15
#   Subject: Printer not working
#   To: helpdesk@letsma.co.uk <helpdesk@letsma.co.uk>
_GMAIL_FORWARD_MARKER_RE = re.compile(r"-{3,}\s*Forwarded message\s*-{3,}", re.IGNORECASE)
_GMAIL_FORWARD_RE = re.compile(
    r"From:\s*(?:(?P<name>[^<\r\n]+?)\s*)?<?(?P<email>[\w.+-]+@[\w-]+\.[\w.-]+)>?\s*[\r\n]+"
    r"Date:\s*(?P<sent>[^\r\n]+)[\r\n]+"
    r"Subject:\s*(?P<subject>[^\r\n]+)[\r\n]+"
    r"To:\s*(?P<to>[^\r\n]+)",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    """Very small, dependency-free HTML-to-text conversion, good enough for
    parsing forwarded email headers (which are plain structured text even
    inside an HTML body)."""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def parse_forwarded_email(subject: str, body_content: str, body_content_type: str = "text"):
    """
    Detects whether an email is a forward and, if so, extracts the
    ORIGINAL sender's name/email and original subject from the quoted
    header block inside the body. Returns None if this doesn't look like
    a forwarded email (i.e. treat it as a direct, first-hand email).

    Returns a dict: {"original_name": str|None, "original_email": str,
                      "original_subject": str, "original_body": str}
    """
    is_fwd_subject = bool(_FWD_SUBJECT_PREFIX_RE.match(subject or ""))

    plain_body = _strip_html(body_content) if body_content_type == "html" else (body_content or "")

    match = _OUTLOOK_FORWARD_RE.search(plain_body)
    if not match and _GMAIL_FORWARD_MARKER_RE.search(plain_body):
        match = _GMAIL_FORWARD_RE.search(plain_body)

    if not match:
        if is_fwd_subject:
            # Subject says "Fwd:" but we couldn't parse a header block -
            # still treat as a forward using the forwarder's own address,
            # just strip the prefix from the subject for a cleaner ticket title.
            return {
                "original_name": None,
                "original_email": None,
                "original_subject": _FWD_SUBJECT_PREFIX_RE.sub("", subject or "").strip(),
                "original_body": plain_body.strip(),
            }
        return None  # not a forward at all

    # Whatever remains after the matched header block is the original message content
    remaining_body = plain_body[match.end():].strip()

    return {
        "original_name": (match.group("name") or "").strip().strip('"') or None,
        "original_email": match.group("email").strip().lower(),
        "original_subject": match.group("subject").strip(),
        "original_body": remaining_body,
    }


# ---------------------------------------------------------------------------
# Auto-reply matching
# ---------------------------------------------------------------------------
def find_matching_auto_reply(subject: str, body: str, db: Session):
    """
    Returns the first ACTIVE AutoReplyRule that matches, or None.

    Each rule's trigger_keywords is a comma-separated list of keyword
    PHRASES (e.g. "password reset,forgot password"). A phrase matches if
    ALL of its individual words appear SOMEWHERE in the subject+body text
    - in any order, not necessarily adjacent. This means "forgot password"
    correctly matches a real email saying "I forgot my password", since
    both words are present, even though a strict substring match would
    miss it. This is intentionally simple, literal word-matching (no
    AI/NLU) so behaviour stays predictable and easy to reason about when
    configuring rules.
    """
    haystack_words = set(re.findall(r"[a-z0-9']+", f"{subject or ''} {body or ''}".lower()))
    rules = db.query(AutoReplyRule).filter_by(active=True).all()
    for rule in rules:
        phrases = [p.strip().lower() for p in rule.trigger_keywords.split(",") if p.strip()]
        for phrase in phrases:
            phrase_words = set(re.findall(r"[a-z0-9']+", phrase))
            if phrase_words and phrase_words.issubset(haystack_words):
                return rule
    return None


# ---------------------------------------------------------------------------
# Customer matching
# ---------------------------------------------------------------------------
def _find_customer_and_contact(db: Session, email_address: str):
    if not email_address:
        return None, None
    contact = db.query(Contact).filter(Contact.email.ilike(email_address)).first()
    if contact:
        return contact.customer, contact
    domain = email_address.split("@")[-1].lower()
    customer = db.query(Customer).filter(Customer.email.ilike(f"%@{domain}")).first()
    return customer, None


# ---------------------------------------------------------------------------
# Sending mail
# ---------------------------------------------------------------------------
async def _send_helpdesk_email(token: str, to_address: str, subject: str, body: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GRAPH_BASE}/users/{settings.HELPDESK_MAILBOX_ADDRESS}/sendMail",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to_address}}],
                },
                "saveToSentItems": True,
            },
        )
        resp.raise_for_status()


async def _mark_email_read(token: str, message_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{GRAPH_BASE}/users/{settings.HELPDESK_MAILBOX_ADDRESS}/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"isRead": True},
        )
        resp.raise_for_status()


# ---------------------------------------------------------------------------
# Core per-email processing
# ---------------------------------------------------------------------------
async def process_single_email(db: Session, token: str, message: dict) -> dict:
    """
    Processes one Graph message dict end-to-end: dedup check, exclusion
    check, forward parsing, ticket creation, auto-reply, confirmation
    email, and marking the source email as read. Returns a summary dict
    describing what happened (useful for logging/testing).
    """
    graph_message_id = message["id"]

    already_processed = db.query(ProcessedEmail).filter_by(graph_message_id=graph_message_id).first()
    if already_processed:
        return {"action": "skipped_duplicate", "graph_message_id": graph_message_id}

    from_email = (message.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
    from_name = (message.get("from") or {}).get("emailAddress", {}).get("name", "")
    subject = message.get("subject", "")
    body_obj = message.get("body", {})
    body_content = body_obj.get("content", "")
    body_content_type = body_obj.get("contentType", "text")

    if is_sender_excluded(from_email, db):
        db.add(ProcessedEmail(
            graph_message_id=graph_message_id, sender_email=from_email,
            subject=subject, was_excluded=True,
        ))
        db.commit()
        await _mark_email_read(token, graph_message_id)
        return {"action": "excluded", "sender": from_email}

    # Determine the "real" sender + subject/body, unwrapping a forward if present
    forward_info = parse_forwarded_email(subject, body_content, body_content_type)
    if forward_info and forward_info["original_email"]:
        effective_email = forward_info["original_email"]
        effective_name = forward_info["original_name"] or effective_email
        effective_subject = forward_info["original_subject"]
        effective_body = forward_info["original_body"]
    elif forward_info:
        # "Fwd:" subject but no parseable header - keep the forwarder as sender
        effective_email = from_email
        effective_name = from_name
        effective_subject = forward_info["original_subject"]
        effective_body = forward_info["original_body"]
    else:
        effective_email = from_email
        effective_name = from_name
        effective_subject = subject
        effective_body = _strip_html(body_content) if body_content_type == "html" else body_content

    customer, contact = _find_customer_and_contact(db, effective_email)

    ticket = None
    if customer:
        ticket = Ticket(
            ticket_number=next_ticket_number(db),
            customer_id=customer.id,
            contact_id=contact.id if contact else None,
            subject=effective_subject[:255] or "(no subject)",
            description=f"From: {effective_name} <{effective_email}>\n\n{effective_body}",
            priority=TicketPriority.NORMAL,
            source=TicketSource.EMAIL,
            external_ref=graph_message_id,
        )
        db.add(ticket)
        db.flush()

    auto_reply_rule = find_matching_auto_reply(effective_subject, effective_body, db)

    processed = ProcessedEmail(
        graph_message_id=graph_message_id, sender_email=effective_email, subject=effective_subject,
        ticket_id=ticket.id if ticket else None, was_excluded=False,
        auto_reply_sent=bool(auto_reply_rule),
    )
    db.add(processed)
    db.commit()

    # Send auto-reply (if matched) and/or a confirmation email
    if effective_email:
        if auto_reply_rule:
            await _send_helpdesk_email(token, effective_email, auto_reply_rule.reply_subject, auto_reply_rule.reply_body)
        if ticket:
            confirmation_body = (
                f"Thanks for contacting Letsma support.\n\n"
                f"We've logged your request as ticket #{ticket.ticket_number}: {ticket.subject}\n\n"
                f"A technician will be in touch shortly. Please quote ticket #{ticket.ticket_number} "
                f"in any further correspondence about this issue."
            )
            await _send_helpdesk_email(token, effective_email, f"Re: {effective_subject} [Ticket #{ticket.ticket_number}]", confirmation_body)

    await _mark_email_read(token, graph_message_id)

    return {
        "action": "ticket_created" if ticket else "no_customer_match",
        "sender": effective_email,
        "ticket_number": ticket.ticket_number if ticket else None,
        "auto_reply_sent": bool(auto_reply_rule),
        "was_forward": bool(forward_info),
    }


# ---------------------------------------------------------------------------
# Polling entry point
# ---------------------------------------------------------------------------
async def poll_and_process_helpdesk_inbox(db: Session) -> dict:
    """Fetches unread messages from the helpdesk inbox and processes each
    one. Safe to call repeatedly (e.g. every few minutes from a scheduled
    job) - already-processed and excluded emails are never re-created."""
    token = await _get_helpdesk_app_token()

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_BASE}/users/{settings.HELPDESK_MAILBOX_ADDRESS}/mailFolders/inbox/messages"
            f"?$filter=isRead eq false&$top=50"
            f"&$select=id,subject,from,body,receivedDateTime",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        messages = resp.json().get("value", [])

    results = []
    for message in messages:
        result = await process_single_email(db, token, message)
        results.append(result)

    return {"messages_found": len(messages), "results": results}
