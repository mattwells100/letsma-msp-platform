"""
app/services/purchase_email_ingestion_service.py

Polls the orders@letsma.co.uk mailbox via Microsoft Graph, turning new
inbound supplier order confirmation emails into draft AmazonOrder records
(your existing general-purpose purchasing table - see the docstring on
AmazonOrder in models.py for why it's named that despite handling any
supplier). Mirrors the structure of email_ingestion_service.py (helpdesk
mailbox polling) so the two features behave consistently:

  - De-duplicates on graph_message_id via ProcessedPurchaseEmail (mirrors
    ProcessedEmail), so re-polling never creates a second order for the
    same email.
  - Also de-duplicates on (supplier, amazon_order_id) in case the same
    order is re-sent/forwarded under a different message id.
  - Downloads PDF/CSV attachments and extracts their text, since several
    suppliers (Misco, Cisco) send order details as a PDF attachment
    rather than in the email body.
  - Uses Azure OpenAI (same gpt-5-mini deployment as ticket-reply drafts)
    to extract a structured purchase record from the email + attachments.
  - Attempts a best-effort customer match; NEVER auto-bills - every
    ingested order lands with extraction_status="needs_review" (source=
    "email_auto") and invoiced=False until a human confirms it via
    /api/purchasing/email-ingestion/{id}/confirm. This is exactly the
    same "unbilled" state your existing purchasing UI already reads for
    manual/CSV-imported orders - email-ingested ones just add the extra
    needs_review gate on top before they're considered trustworthy.
  - Marks the source email as read once processed (matching the helpdesk
    poller's behaviour).

Reuses the SAME Entra ID app registration/credentials as the helpdesk
mailbox poller (settings.HELPDESK_GRAPH_*), since both mailboxes live in
Letsma's own tenant. See README_SETUP.md for the Exchange Application
Access Policy change this requires.
"""
import base64
import io
import json
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AmazonOrder, AmazonOrderLineItem, Customer, Contact, ProcessedPurchaseEmail
from app.services.azure_openai_service import extract_purchase_from_email

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
async def _get_orders_app_token() -> str:
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
# Attachment text extraction
# ---------------------------------------------------------------------------
def _extract_pdf_text(raw_bytes: bytes) -> str:
    """Best-effort text extraction from a PDF attachment. Returns "" on
    any failure rather than raising, since a missing attachment text
    should not block the whole email from being processed - the AI
    extraction step will just have less to work with."""
    try:
        import pdfplumber

        text_chunks = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_chunks.append(page_text)
        return "\n".join(text_chunks)
    except Exception:
        return ""


async def _get_attachment_texts(token: str, message_id: str) -> list:
    """Returns a list of extracted text strings, one per PDF/CSV
    attachment on the message. Non-text attachment types are skipped."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_BASE}/users/{settings.ORDERS_MAILBOX_ADDRESS}/messages/{message_id}/attachments",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        attachments = resp.json().get("value", [])

    texts = []
    for att in attachments:
        name = (att.get("name") or "").lower()
        content_type = att.get("contentType", "")
        content_bytes = att.get("contentBytes")
        if not content_bytes:
            continue
        raw = base64.b64decode(content_bytes)
        if name.endswith(".csv") or "csv" in content_type:
            texts.append(raw.decode("utf-8", errors="ignore"))
        elif name.endswith(".pdf") or "pdf" in content_type:
            pdf_text = _extract_pdf_text(raw)
            if pdf_text:
                texts.append(pdf_text)
    return texts


# ---------------------------------------------------------------------------
# Customer matching
# ---------------------------------------------------------------------------
def _find_customer_id(db: Session, company_name, email_address):
    """
    Best-effort customer match. Returns customer_id (str) or None.
    Deliberately conservative - a wrong auto-match is worse than none,
    since it would silently attach a purchase to the wrong customer's
    invoice. Mirrors the approach in email_ingestion_service's customer
    matching: contact/customer email first, then a fuzzy company-name
    fallback against Customer.name.
    """
    if email_address and "@" in email_address:
        contact = db.query(Contact).filter(Contact.email.ilike(email_address)).first()
        if contact and contact.customer_id:
            return contact.customer_id
        domain = email_address.split("@")[-1].lower()
        customer = db.query(Customer).filter(Customer.email.ilike(f"%@{domain}")).first()
        if customer:
            return customer.id

    if company_name:
        customer = db.query(Customer).filter(Customer.name.ilike(f"%{company_name.strip()}%")).first()
        if customer:
            return customer.id

    return None


# ---------------------------------------------------------------------------
# Mark as read
# ---------------------------------------------------------------------------
async def _mark_email_read(token: str, message_id: str):
    async with httpx.AsyncClient() as client:
        resp = await client.patch(
            f"{GRAPH_BASE}/users/{settings.ORDERS_MAILBOX_ADDRESS}/messages/{message_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"isRead": True},
        )
        resp.raise_for_status()


def _make_order_reference(order_number, graph_message_id: str) -> str:
    """
    AmazonOrder.amazon_order_id is NOT NULL and UNIQUE, since it's also
    used as the dedup key for CSV imports. Use the extracted supplier
    order number when available (the common case - most confirmations do
    include one); fall back to a message-derived reference when the
    extraction genuinely couldn't find one, so the row can still be
    created without violating the unique constraint.
    """
    if order_number:
        return str(order_number).strip()
    return f"EMAIL-{graph_message_id[-40:]}"


# ---------------------------------------------------------------------------
# Core per-email processing
# ---------------------------------------------------------------------------
async def process_single_order_email(db: Session, token: str, message: dict) -> dict:
    """
    Processes one Graph message dict end-to-end: dedup check, attachment
    text extraction, AI extraction, customer matching, draft AmazonOrder
    (+ line items) creation, and marking the source email as read.
    Returns a summary dict describing what happened (useful for
    logging/testing).
    """
    graph_message_id = message["id"]

    already_processed = db.query(ProcessedPurchaseEmail).filter_by(graph_message_id=graph_message_id).first()
    if already_processed:
        return {"action": "skipped_duplicate", "graph_message_id": graph_message_id}

    subject = message.get("subject", "")
    body_obj = message.get("body", {})
    body_content = body_obj.get("content", "")
    has_attachments = message.get("hasAttachments", False)

    attachment_texts = []
    if has_attachments:
        try:
            attachment_texts = await _get_attachment_texts(token, graph_message_id)
        except Exception:
            attachment_texts = []  # extraction still proceeds on email body alone

    try:
        extracted = await extract_purchase_from_email(subject, body_content, attachment_texts)
        extraction_error = None
    except Exception as exc:
        extracted = {}
        extraction_error = str(exc)

    supplier = extracted.get("supplier") or "Unknown"
    order_number = extracted.get("order_number")
    order_reference = _make_order_reference(order_number, graph_message_id)

    # Secondary dedup: same supplier + order reference already ingested
    # (catches a supplier re-sending/re-forwarding the same order under a
    # different message id).
    dup = (
        db.query(AmazonOrder)
        .filter(AmazonOrder.supplier == supplier, AmazonOrder.amazon_order_id == order_reference)
        .first()
    )
    if dup:
        db.add(ProcessedPurchaseEmail(graph_message_id=graph_message_id, subject=subject, order_id=dup.id))
        db.commit()
        await _mark_email_read(token, graph_message_id)
        return {"action": "skipped_duplicate_order", "supplier": supplier, "order_reference": order_reference}

    customer_id = _find_customer_id(db, extracted.get("end_user_company"), extracted.get("end_user_email"))

    end_user_hint = None
    if extracted.get("end_user_company") or extracted.get("end_user_email"):
        end_user_hint = f"{extracted.get('end_user_company') or ''} <{extracted.get('end_user_email') or ''}>".strip()

    order_date = None
    if extracted.get("order_date"):
        try:
            order_date = datetime.fromisoformat(extracted["order_date"])
        except (ValueError, TypeError):
            order_date = None  # leave null rather than guess a malformed date

    order = AmazonOrder(
        amazon_order_id=order_reference,
        customer_id=customer_id,
        supplier=supplier,
        order_date=order_date,
        total=extracted.get("total_inc_vat") or 0.0,
        currency=extracted.get("currency") or "GBP",
        description=subject[:500] if subject else None,
        source="email_auto",
        invoiced=False,
        extraction_status="failed" if extraction_error else "needs_review",
        raw_extraction_json=json.dumps(extracted if not extraction_error else {"error": extraction_error, "subject": subject}),
        end_user_hint=end_user_hint,
        imported_at=datetime.utcnow(),
        ingested_at=datetime.utcnow(),
    )
    db.add(order)
    db.flush()  # populate order.id before creating line items

    for item in extracted.get("line_items") or []:
        db.add(AmazonOrderLineItem(
            order_id=order.id,
            description=(item.get("description") or "Unknown item")[:255],
            quantity=item.get("quantity") or 1.0,
            unit_price=item.get("unit_cost") or 0.0,
        ))

    db.add(ProcessedPurchaseEmail(graph_message_id=graph_message_id, subject=subject, order_id=order.id))
    db.commit()

    await _mark_email_read(token, graph_message_id)

    return {
        "action": "ingested" if not extraction_error else "ingested_extraction_failed",
        "order_id": order.id,
        "supplier": supplier,
        "order_reference": order_reference,
        "customer_matched": bool(customer_id),
    }


# ---------------------------------------------------------------------------
# Polling entry point
# ---------------------------------------------------------------------------
async def poll_and_process_orders_inbox(db: Session) -> dict:
    """Fetches unread messages from the orders inbox and processes each
    one. Safe to call repeatedly (e.g. every few minutes from a scheduled
    job) - already-processed emails are never re-ingested."""
    token = await _get_orders_app_token()

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GRAPH_BASE}/users/{settings.ORDERS_MAILBOX_ADDRESS}/mailFolders/inbox/messages"
            f"?$filter=isRead eq false&$top=50"
            f"&$select=id,subject,from,body,receivedDateTime,hasAttachments",
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        messages = resp.json().get("value", [])

    results = []
    for message in messages:
        result = await process_single_order_email(db, token, message)
        results.append(result)

    return {"messages_found": len(messages), "results": results}
