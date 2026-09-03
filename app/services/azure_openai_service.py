"""
app/services/azure_openai_service.py

Thin wrapper around the Azure OpenAI Chat Completions REST API. Used for:
  1. draft_ticket_reply() - drafts (never auto-sends) suggested replies to
     helpdesk tickets. A technician always reviews and edits the
     suggestion before it's posted - this only ever returns a draft
     string, it never writes to the database or sends anything itself.
  2. extract_purchase_from_email() - extracts a structured purchase record
     (supplier, order number, line items, prices) from a supplier order
     confirmation email for the purchasing-email-ingest feature. Like the
     ticket-reply draft, this NEVER writes billing data directly - the
     caller always lands the result in a needs_review state for a human
     to confirm before anything becomes billable.

Uses plain httpx REST calls (consistent with how Xero/Graph are already
integrated elsewhere in this codebase) rather than adding the `openai`
Python package as a new dependency.

IMPORTANT model note (as of August 2026): gpt-4o-mini was retired for
Standard deployments on 31 March 2026. The recommended replacement,
gpt-4.1-mini, is itself scheduled to retire on 14 October 2026. This
service is instead built for gpt-5-mini (GA, scheduled retirement not
until Feb 2027), which is also cheaper per-token than gpt-4.1-mini.

gpt-5-series models are "reasoning models" on the Chat Completions API
and behave differently from older models in two important ways:
  1. They do NOT support temperature/top_p/penalty parameters.
  2. They spend part of max_completion_tokens on invisible internal
     "reasoning tokens" BEFORE writing the visible reply - if the budget
     is too low, the model can use it all up thinking and return an
     EMPTY string with no error (this is a widely-reported gotcha, not
     a bug in this code). max_completion_tokens is therefore set
     generously here (2000) to comfortably cover both the reasoning
     overhead and a genuinely useful reply, rather than the ~400 that
     would be typical for an older non-reasoning chat model.
"""
import json

import httpx

from app.config import settings

# Chat Completions REST endpoint format:
#   https://<resource>.openai.azure.com/openai/deployments/<deployment>/chat/completions?api-version=...
AZURE_OPENAI_API_VERSION = "2024-08-01-preview"

_SYSTEM_PROMPT = """You are an assistant helping an IT Managed Service Provider's helpdesk technician draft a reply to a customer support ticket.

Rules you must follow:
- Write ONLY the reply text itself - no preamble like "Here's a draft:", no explanation of what you did.
- Be professional, warm, and concise. Match a typical UK business tone.
- Base your reply STRICTLY on the information given in the ticket below. Do NOT invent facts, dates, prices, order numbers, or promises that aren't stated in the ticket.
- If the ticket doesn't contain enough information to give a useful answer, write a reply that asks the customer a clarifying question instead of guessing.
- Never promise a specific fix time, refund, or compensation - leave that to the technician to decide and add themselves if appropriate.
- Sign off with "Best regards," on its own line, followed by a blank placeholder line for the technician's name (do not invent a name).
"""


def _build_ticket_context(ticket_subject: str, ticket_description: str, customer_name: str, comments: list) -> str:
    lines = [
        f"Customer: {customer_name}",
        f"Ticket subject: {ticket_subject}",
        f"Original description: {ticket_description or '(no description provided)'}",
    ]
    if comments:
        lines.append("\nConversation so far (oldest first):")
        for c in comments:
            if c.get("is_internal_note"):
                continue  # never leak internal-only notes into a customer-facing draft
            lines.append(f"- {c['author']}: {c['message']}")
    else:
        lines.append("\n(No replies yet - this would be the first response.)")
    return "\n".join(lines)


async def draft_ticket_reply(ticket_subject: str, ticket_description: str, customer_name: str, comments: list) -> str:
    """
    Calls Azure OpenAI to draft a suggested reply for a helpdesk ticket.
    Returns the suggested reply text as a plain string. Raises on any
    HTTP/config error - the caller is expected to surface this clearly
    rather than silently falling back to something misleading.

    If Azure genuinely returns an empty string even with a generous
    token budget (e.g. if a future model needs even more headroom),
    this raises a clear RuntimeError rather than silently returning ""
    to the technician, which would look like the button just didn't work.
    """
    if not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_API_KEY or not settings.AZURE_OPENAI_DEPLOYMENT_NAME:
        raise RuntimeError(
            "Azure OpenAI is not configured yet. Set AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT_NAME in Key Vault, then restart the app."
        )

    context = _build_ticket_context(ticket_subject, ticket_description, customer_name, comments)

    url = (
        f"{settings.AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{settings.AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions"
        f"?api-version={AZURE_OPENAI_API_VERSION}"
    )

    payload = {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        # gpt-5-series reasoning models do NOT support temperature/top_p/
        # penalty parameters, and use max_completion_tokens instead of
        # max_tokens. This budget is set generously (2000, not ~400)
        # because reasoning models consume part of it on invisible
        # internal reasoning before writing the visible reply - too low
        # a budget causes an EMPTY (but technically successful, no
        # error) response, which is a widely-reported gotcha with these
        # models rather than a bug in this integration.
        "max_completion_tokens": 2000,
    }

    async with httpx.AsyncClient(timeout=45.0) as client:
        resp = await client.post(
            url,
            headers={"api-key": settings.AZURE_OPENAI_API_KEY, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    draft = data["choices"][0]["message"]["content"].strip()

    if not draft:
        finish_reason = data["choices"][0].get("finish_reason", "unknown")
        usage = data.get("usage", {})
        raise RuntimeError(
            f"Azure OpenAI returned an empty reply (finish_reason={finish_reason}, "
            f"usage={usage}). This usually means the model used its entire token "
            f"budget on internal reasoning - try again, or contact support if this persists."
        )

    return draft


# ---------------------------------------------------------------------------
# Purchase extraction (purchasing-email-ingest feature)
# ---------------------------------------------------------------------------
_PURCHASE_EXTRACTION_SYSTEM_PROMPT = """You are a data-extraction engine for an IT Managed Service Provider's purchasing system.

You will be given the text of a supplier order confirmation or shipment notification email (and optionally attachment text, e.g. from a PDF or CSV). Extract the purchase into JSON matching exactly this shape:

{
  "supplier": string,                 // e.g. "Misco", "CloudControlled", "Cisco", "Ingram Micro", "Broadbandbuyer"
  "order_number": string or null,      // supplier's order/reference number
  "order_date": string or null,        // ISO 8601 date, YYYY-MM-DD, if stated
  "end_user_company": string or null,  // the customer this was ordered for/shipped to, if stated
  "end_user_email": string or null,
  "currency": string,                 // ISO code, default "GBP" if not stated
  "line_items": [
    {
      "description": string,
      "sku": string or null,
      "quantity": number,
      "unit_cost": number,
      "line_total": number
    }
  ],
  "subtotal_ex_vat": number or null,
  "vat": number or null,
  "total_inc_vat": number or null,
  "confidence": number                // your own confidence in this extraction, 0.0 to 1.0
}

Rules you must follow:
- If a field is not present in the source text, use null (or [] for line_items) rather than guessing.
- Never invent an order number, price, or company name that is not present in the text.
- Output ONLY the JSON object - no preamble, no explanation, no markdown code fences.
"""


def _build_purchase_context(email_subject: str, email_body_text: str, attachment_texts: list) -> str:
    lines = [f"SUBJECT: {email_subject}", "", "EMAIL BODY:", email_body_text or "(no body text)"]
    for i, att_text in enumerate(attachment_texts or [], start=1):
        if att_text:
            lines.append(f"\nATTACHMENT {i} TEXT:\n{att_text}")
    # Guard against oversized attachments blowing the context window.
    return "\n".join(lines)[:12000]


async def extract_purchase_from_email(email_subject: str, email_body_text: str, attachment_texts: list) -> dict:
    """
    Calls Azure OpenAI to extract a structured purchase record from a
    supplier order email. Returns the parsed dict. Raises RuntimeError on
    any config/HTTP error, an empty response, or unparseable JSON - the
    caller (purchase_email_ingestion_service) is expected to catch this
    and route the email to a "needs_review" / "failed" state rather than
    letting the whole polling job crash on one bad email.

    Same gpt-5-mini reasoning-model handling as draft_ticket_reply:
    no temperature/top_p, and a generous max_completion_tokens budget
    since reasoning tokens are spent before the visible JSON is written.
    """
    if not settings.AZURE_OPENAI_ENDPOINT or not settings.AZURE_OPENAI_API_KEY or not settings.AZURE_OPENAI_DEPLOYMENT_NAME:
        raise RuntimeError(
            "Azure OpenAI is not configured yet. Set AZURE_OPENAI_ENDPOINT, "
            "AZURE_OPENAI_API_KEY, and AZURE_OPENAI_DEPLOYMENT_NAME in Key Vault, then restart the app."
        )

    context = _build_purchase_context(email_subject, email_body_text, attachment_texts)

    url = (
        f"{settings.AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/"
        f"{settings.AZURE_OPENAI_DEPLOYMENT_NAME}/chat/completions"
        f"?api-version={AZURE_OPENAI_API_VERSION}"
    )

    payload = {
        "messages": [
            {"role": "system", "content": _PURCHASE_EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": context},
        ],
        # See draft_ticket_reply() above for why no temperature/top_p and
        # why max_completion_tokens is generous (2000) for gpt-5-mini.
        "max_completion_tokens": 2000,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            url,
            headers={"api-key": settings.AZURE_OPENAI_API_KEY, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()

    if not content:
        finish_reason = data["choices"][0].get("finish_reason", "unknown")
        usage = data.get("usage", {})
        raise RuntimeError(
            f"Azure OpenAI returned an empty extraction (finish_reason={finish_reason}, "
            f"usage={usage}). This usually means the model used its entire token "
            f"budget on internal reasoning - the email should be retried or reviewed manually."
        )

    # Models occasionally wrap JSON in markdown fences despite instructions -
    # strip those defensively before parsing.
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse Azure OpenAI output as JSON: {exc}. Raw content: {content[:500]}") from exc
