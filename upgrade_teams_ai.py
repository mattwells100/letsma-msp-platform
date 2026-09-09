from pathlib import Path
from datetime import datetime
import shutil

p = Path("app/routers/teams_bot.py")

backup = f"{p}.bak-{datetime.now():%Y%m%d-%H%M%S}"
shutil.copy2(p, backup)

txt = p.read_text(encoding="utf-8")

# Extra imports
txt = txt.replace(
    "from app.services.ticket_numbering import next_ticket_number",
    """from app.services.ticket_numbering import next_ticket_number
from app.routers.ai_assist import (
    _parse_ticket_classification,
    AI_TICKET_CATEGORIES,
)
from app.services import azure_openai_service
import json"""
)

old = """    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    return {
        "type": "message",
        "text": f"✅ Ticket #{ticket.ticket_number} created"
    }
"""

new = r'''    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    try:
        prompt = (
            "Return exactly one JSON object with no Markdown. "
            "The keys must be category, subcategory, priority, "
            "estimated_minutes, confidence and reason.\\n\\n"
            "Allowed categories and subcategories:\\n"
            f"{json.dumps(AI_TICKET_CATEGORIES)}\\n\\n"
            "Priority must be Low, Normal, High or Critical. "
            "Confidence must be Low, Medium or High. "
            "estimated_minutes must be between 5 and 480. "
            "Use only the supplied ticket evidence and do not invent facts.\\n\\n"
            f"Ticket description:\\n{text}"
        )

        raw_result = await azure_openai_service.draft_ticket_reply(
            ticket_subject=f"Ticket categorisation: {ticket.subject}",
            ticket_description=prompt,
            customer_name="Teams User",
            comments=[],
        )

        suggestion = _parse_ticket_classification(raw_result)

        ticket.category = suggestion.get("category")
        ticket.subcategory = suggestion.get("subcategory")
        ticket.estimated_minutes = suggestion.get("estimated_minutes")

        db.add(ticket)
        db.commit()
        db.refresh(ticket)

    except Exception as exc:
        print("Teams AI classification failed:", exc)

    return {
        "type": "message",
        "text": (
            f"✅ Ticket #{ticket.ticket_number} created\\n\\n"
            f"Category: {ticket.category or 'Pending'}\\n"
            f"Subcategory: {ticket.subcategory or 'Pending'}\\n"
            f"Estimate: {ticket.estimated_minutes or '-'} mins"
        )
    }
'''

txt = txt.replace(old, new)

p.write_text(txt, encoding="utf-8")

print("[OK] Teams AI classification enabled")
print("[OK] Backup:", backup)