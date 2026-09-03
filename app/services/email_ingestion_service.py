"""
app/services/email_ingestion_service.py

Polls the helpdesk@letsma.co.uk mailbox via Microsoft Graph, turning new
inbound emails into helpdesk tickets automatically. Handles:
  - Excluding specific senders/domains from ever creating a ticket
  - Detecting forwarded emails and extracting the ORIGINAL sender's
    details (so a ticket is correctly attributed to the customer who
    actually emailed, not the staff member who forwarded it)
  - Matching against simple keyword-triggered auto-reply rules
  - De-duplicating so re-polling never creates a second ticket for the
    same email
  - Creating a ticket even when no customer can be matched - customer_id
    is simply left null and the original sender's name/email are
    preserved on reporter_name/reporter_email, so a technician can
    review and manually assign the right customer afterwards, rather
    than the email being silently dropped.

TICKET DESCRIPTION FORMATTING: the description is stored as just the
CLEAN message body (no "From: X <Y>" prefix) - who reported the ticket
is instead shown properly in the ticket detail page UI (via contact_id /
reporter_name / reporter_email), so it isn't duplicated as unstructured
text at the top of the description. _strip_html() converts a much wider
set of block-level HTML tags to newlines than a naive <br>-only approach,
since Outlook/Exchange HTML emails commonly use <div>/<tr>/<li> for
structure rather than <br> - without this, unrelated lines get squashed
together into an unreadable wall of text once rendered.

OUTBOUND EMAIL IS DISABLED BY DEFAULT: neither the keyword-triggered
auto-reply nor the "we've logged your ticket" confirmation email is sent
unless settings.HELPDESK_AUTO_REPLIES_ENABLED is explicitly set to true.
This lets ticket ingestion (matching, forwarded-email parsing, exclusion
list, ticket creation) run safely against a real mailbox with ZERO risk
of an unintended email reaching a real customer. Flip
HELPDESK_AUTO_REPLIES_ENABLED on only once you've reviewed a batch of
auto-created tickets and are confident in the setup.

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

# Block-level HTML tags whose CLOSE (or self-closing form, for <br>) should
# become a newline when converting to plain text. Deliberately wider than
# just <br>/</p> - Outlook/Exchange HTML emails frequently use <div>, table
# rows/cells, and list items for layout rather than <br>, and without this
# those all get squashed onto one line, producing an unreadable wall of
# text once rendered in the ticket description.
_BLOCK_CLOSE_TAGS_RE = re.compile(
    r"</?(?:br|p|div|tr|td|li|h[1-6]|table|ul|ol)\s*/?>",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    """
    Dependency-free HTML-to-text conversion good enough for both parsing
    forwarded email headers (plain structured text even inside an HTML
    body) and producing a readable plain-text ticket description.
    Converts a wide set of block-level tags to newlines (see
    _BLOCK_CLOSE_TAGS_RE), strips all remaining tags, unescapes HTML
    entities, then collapses 3+ consecutive blank lines down to a single
    blank line and trims leading/trailing whitespace - without this,
    heavily-nested HTML emails can produce dozens of stray blank lines.

    Also converts non-breaking spaces (\\xa0) to regular spaces BEFORE
    blank-line collapsing - Outlook commonly inserts "<div>&nbsp;</div>"
    as a spacer between paragraphs, and &nbsp; unescapes to \\xa0 rather
    than a plain space, which would otherwise dodge the blank-line
    detection below and leave visually-blank-but-not-empty lines behind.
    """
    text = _BLOCK_CLOSE_TAGS_RE.sub("\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    lines = [line.rstrip() for line in text.split("\n")]  # strip trailing whitespace per line
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)        # collapse excessive blank lines
    return text.strip()


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

    Note: matching still runs unconditionally so the result can be
    reported (auto_reply_would_send) even while outbound email is
    disabled - it is only ever ACTED on (i.e. an email actually sent)
    when settings.HELPDESK_AUTO_REPLIES_ENABLED is true, see
    process_single_email() below.

    Each rule's trigger_keywords is a comma-separated list of keyword
    PHRASES (e.g. "password reset,forgot password"). A phrase matches if
    ALL of its individual words appear SOMEWHERE in the subject+body text
    - in any order, not necessarily adjacent.
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
    """
    Returns (customer, contact) - either or both may be None if no match
    is found. A ticket is ALWAYS still created in that case (see
    process_single_email below) - it's simply left unassigned
    (customer_id/contact_id null) rather than dropped.
    """
    if not email_address:
        return None, None
    contact = db.query(Contact).filter(Contact.email.ilike(email_address)).first()
    if contact:
        return contact.customer, contact
    domain = email_address.split("@")[-1].lower()
    customer = db.query(Customer).filter(Customer.email.ilike(f"%@{domain}")).first()
    return customer, None


# ---------------------------------------------------------------------------
# Sending mail (gated behind settings.HELPDESK_AUTO_REPLIES_ENABLED)
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
    check, forward parsing, ticket creation (with or without a matched
    customer), auto-reply/confirmation email (ONLY if explicitly
    enabled), and marking the source email as read. Returns a summary
    dict describing what happened (useful for logging/testing).
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

    # Determine the "real" sender + subject/body, unwrapping a forward if
    # present - this is what lets a ticket be correctly attributed to the
    # CUSTOMER who originally emailed, even when a staff member forwards
    # it into the helpdesk mailbox on their behalf.
    forward_info = parse_forwarded_email(subject, body_content, body_content_type)
    if forward_info and forward_info["original_email"]:
        effective_email = forward_info["original_email"]
        effective_name = forward_info["original_name"] or effective_email
        effective_subject = forward_info["original_subject"]
        effective_body = forward_info["original_body"]
        was_forward = True
    elif forward_info:
        # "Fwd:" subject but no parseable header - keep the forwarder as sender
        effective_email = from_email
        effective_name = from_name
        effective_subject = forward_info["original_subject"]
        effective_body = forward_info["original_body"]
        was_forward = True
    else:
        effective_email = from_email
        effective_name = from_name
        effective_subject = subject
        effective_body = _strip_html(body_content) if body_content_type == "html" else body_content
        was_forward = False

    customer, contact = _find_customer_and_contact(db, effective_email)

    # ALWAYS create a ticket, even when no customer could be matched.
    # customer_id/contact_id are simply left null in that case, and the
    # original reporter's name/email are preserved on the ticket itself
    # so a technician can review and manually assign the right customer
    # later via the ticket detail page.
    #
    # The description stores ONLY the clean message body - who sent it is
    # deliberately NOT prefixed here as "From: X <Y>" text, since that
    # information is preserved structurally on reporter_name/
    # reporter_email/contact_id and shown properly in the ticket detail
    # page UI. Embedding it as unstructured text at the top of the body
    # both duplicates that display and makes the description harder to
    # read.
    ticket = Ticket(
        ticket_number=next_ticket_number(db),
        customer_id=customer.id if customer else None,
        contact_id=contact.id if contact else None,
        reporter_name=effective_name or None,
        reporter_email=effective_email or None,
        subject=effective_subject[:255] or "(no subject)",
        description=effective_body.strip() or "(no message content)",
        priority=TicketPriority.NORMAL,
        source=TicketSource.EMAIL,
        external_ref=graph_message_id,
    )
    db.add(ticket)
    db.flush()

    auto_reply_rule = find_matching_auto_reply(effective_subject, effective_body, db)
    auto_reply_would_send = bool(auto_reply_rule)
    auto_reply_actually_sent = False

    processed = ProcessedEmail(
        graph_message_id=graph_message_id, sender_email=effective_email, subject=effective_subject,
        ticket_id=ticket.id, was_excluded=False,
        auto_reply_sent=False,  # updated below only if actually sent
    )
    db.add(processed)
    db.commit()

    # Outbound email is DISABLED BY DEFAULT (see module docstring) - only
    # send anything if explicitly enabled via settings.
    if settings.HELPDESK_AUTO_REPLIES_ENABLED and effective_email:
        if auto_reply_rule:
            await _send_helpdesk_email(token, effective_email, auto_reply_rule.reply_subject, auto_reply_rule.reply_body)
            auto_reply_actually_sent = True

        confirmation_body = (
            f"Thanks for contacting Letsma support.\n\n"
            f"We've logged your request as ticket #{ticket.ticket_number}: {ticket.subject}\n\n"
            f"A technician will be in touch shortly. Please quote ticket #{ticket.ticket_number} "
            f"in any further correspondence about this issue."
        )
        await _send_helpdesk_email(token, effective_email, f"Re: {effective_subject} [Ticket #{ticket.ticket_number}]", confirmation_body)

        processed.auto_reply_sent = auto_reply_actually_sent
        db.commit()

    await _mark_email_read(token, graph_message_id)

    return {
        "action": "ticket_created" if customer else "ticket_created_unassigned",
        "sender": effective_email,
        "ticket_number": ticket.ticket_number,
        "customer_matched": bool(customer),
        "auto_reply_would_send": auto_reply_would_send,
        "auto_reply_actually_sent": auto_reply_actually_sent,
        "was_forward": was_forward,
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
