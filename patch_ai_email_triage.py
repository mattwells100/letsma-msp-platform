#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import shutil
import py_compile

STAMP = datetime.now().strftime("%Y%m%d-%H%M%S")

SERVICE = Path("app/services/email_ingestion_service.py")

backup = f"{SERVICE}.bak-{STAMP}"
shutil.copy2(SERVICE, backup)
print(f"[BACKUP] {backup}")

text = SERVICE.read_text(encoding="utf-8")

# -------------------------------------------------------
# Imports
# -------------------------------------------------------

if "from app.services.ai_service import" not in text:
    text = text.replace(
        "from app.services.ticket_numbering import next_ticket_number",
        """from app.services.ticket_numbering import next_ticket_number
from app.services.ai_service import get_openai_client"""
    )

# -------------------------------------------------------
# AI triage function
# -------------------------------------------------------

marker = "# ---------------------------------------------------------------------------\n# Reply detection (conversation threading)"

if "async def classify_helpdesk_email" not in text:

    ai_block = '''

# ---------------------------------------------------------------------------
# AI Email Triage
# ---------------------------------------------------------------------------
async def classify_helpdesk_email(subject: str, body: str) -> dict:
    """
    Uses Azure OpenAI to determine whether an email
    is genuinely a helpdesk request.

    Returns:
    {
        "classification": "HELPDESK",
        "confidence": 0.95
    }
    """

    try:
        client = get_openai_client()

        prompt = f"""
You are a managed service provider helpdesk triage assistant.

Classify this email into ONE category:

HELPDESK
ORDERS
INVOICE
RENEWAL
MARKETING
NEWSLETTER
ALERT
OTHER

Return JSON only.

Subject:
{subject}

Body:
{body[:4000]}
"""

        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Return JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
        )

        import json

        result = json.loads(
            resp.choices[0].message.content
        )

        return result

    except Exception as exc:
        print(f"EMAIL_TRIAGE_FAILED: {exc}")

        return {
            "classification": "HELPDESK",
            "confidence": 0.50,
        }

'''

    text = text.replace(marker, ai_block + "\n" + marker)

# -------------------------------------------------------
# Insert AI gate before ticket creation
# -------------------------------------------------------

old = "customer, contact = _find_customer_and_contact(db, effective_email)"

new = """
    triage = await classify_helpdesk_email(
        effective_subject,
        effective_body
    )

    classification = str(
        triage.get("classification", "OTHER")
    ).upper()

    confidence = float(
        triage.get("confidence", 0)
    )

    print(
        f"EMAIL_TRIAGE "
        f"classification={classification} "
        f"confidence={confidence} "
        f"subject={effective_subject[:80]}"
    )

    if classification != "HELPDESK":

        db.add(
            ProcessedEmail(
                graph_message_id=graph_message_id,
                sender_email=effective_email,
                subject=effective_subject,
                was_excluded=True,
            )
        )

        db.commit()

        await _mark_email_read(
            token,
            graph_message_id
        )

        return {
            "action": "ignored_non_helpdesk",
            "classification": classification,
            "confidence": confidence,
            "sender": effective_email,
        }

    customer, contact = _find_customer_and_contact(
        db,
        effective_email
    )
"""

text = text.replace(old, new)

SERVICE.write_text(text, encoding="utf-8")

print("[OK] AI triage added")

# -------------------------------------------------------
# Compile
# -------------------------------------------------------

try:
    py_compile.compile(
        str(SERVICE),
        doraise=True
    )

    print("[COMPILE OK]")

except Exception as exc:
    print(f"[COMPILE FAIL] {exc}")