from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/ai_assist.py")

text = p.read_text(encoding="utf-8")

backup = f"{p}.bak-debug-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

old = """        raw_result = await azure_openai_service.draft_ticket_reply(
            ticket_subject=f"Ticket categorisation: {ticket.subject}",
            ticket_description=prompt,
            customer_name=(
                customer.name
                if customer
                else "Unknown customer"
            ),
            comments=comments_data,
        )

        suggestion = _parse_ticket_classification(raw_result)
"""

new = """        raw_result = await azure_openai_service.draft_ticket_reply(
            ticket_subject=f"Ticket categorisation: {ticket.subject}",
            ticket_description=prompt,
            customer_name=(
                customer.name
                if customer
                else "Unknown customer"
            ),
            comments=comments_data,
        )

        print("=" * 80)
        print("AI CLASSIFICATION RAW RESPONSE")
        print(raw_result)
        print("=" * 80)

        suggestion = _parse_ticket_classification(raw_result)
"""

if old not in text:
    raise SystemExit("Could not find insertion point")

text = text.replace(old, new, 1)

p.write_text(text, encoding="utf-8")

print("[OK] Debug logging added")
print(f"[OK] Backup written: {backup}")
``