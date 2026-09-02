"""
app/services/azure_openai_service.py

Thin wrapper around the Azure OpenAI Chat Completions REST API, used to
draft (never auto-send) suggested replies to helpdesk tickets. A
technician always reviews and edits the suggestion before it's posted -
this service only ever returns a draft string, it never writes to the
database or sends anything itself.

Uses plain httpx REST calls (consistent with how Xero/Graph are already
integrated elsewhere in this codebase) rather than adding the `openai`
Python package as a new dependency.

IMPORTANT model note (as of August 2026): gpt-4o-mini was retired for
Standard deployments on 31 March 2026. The recommended replacement,
gpt-4.1-mini, is itself scheduled to retire on 14 October 2026. This
service is instead built for gpt-5-mini (GA, scheduled retirement not
until Feb 2027), which is also cheaper per-token than gpt-4.1-mini.

gpt-5-series models are "reasoning models" on the Chat Completions API
and behave differently from older models: they do NOT support
temperature/top_p/penalty parameters, and use max_completion_tokens
instead of max_tokens. This payload is built accordingly.
"""
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
        # gpt-5-series models are "reasoning models" on this API and do
        # NOT support temperature/top_p/penalty parameters - omitting
        # temperature entirely (rather than sending a default) avoids an
        # "unsupported parameter" error. max_completion_tokens replaces
        # max_tokens for these models.
        "max_completion_tokens": 400,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            headers={"api-key": settings.AZURE_OPENAI_API_KEY, "Content-Type": "application/json"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"].strip()
