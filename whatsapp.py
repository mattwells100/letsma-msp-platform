from pathlib import Path
from datetime import datetime
import shutil
import re
import py_compile
import sys

FILE = Path("app/services/whatsapp_service.py")

if not FILE.exists():
    print("ERROR: whatsapp_service.py not found")
    sys.exit(1)

backup = FILE.with_suffix(
    FILE.suffix + f".bak-whatsapp-ai-{datetime.now():%Y%m%d-%H%M%S}"
)
shutil.copy2(FILE, backup)
print(f"Backup created: {backup}")

text = FILE.read_text(encoding="utf-8")

# ------------------------------------------------------------------
# Add imports if missing
# ------------------------------------------------------------------

imports_to_add = """
from app.services import azure_openai_service
from app.routers.teams_bot import (
    AI_TICKET_CATEGORIES,
    _parse_ticket_classification,
)
"""

if "AI_TICKET_CATEGORIES" not in text:
    text = text.replace(
        "from app.services.whatsapp_service import",
        imports_to_add + "\nfrom app.services.whatsapp_service import",
    )

if "from app.services import azure_openai_service" not in text:
    insert_after = "from app.config import settings"
    if insert_after in text:
        text = text.replace(
            insert_after,
            insert_after + "\n" + imports_to_add
        )

# ------------------------------------------------------------------
# Inject AI classification block
# ------------------------------------------------------------------

target = """
                    db.add(ticket)
                    is_new = True
"""

classification_block = """
                    db.add(ticket)
                    is_new = True

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
                            "Use only the supplied ticket evidence and do not invent facts."
                            "\\n\\n"
                            f"Ticket description:\\n{body}"
                        )

                        raw_result = await azure_openai_service.classify_ticket(
                            prompt,
                            allowed_categories=AI_TICKET_CATEGORIES,
                        )

                        suggestion = _parse_ticket_classification(raw_result)

                        ticket.category = suggestion.get("category")
                        ticket.subcategory = suggestion.get("subcategory")
                        ticket.estimated_minutes = suggestion.get("estimated_minutes")

                    except Exception as exc:
                        print(
                            "WHATSAPP_CLASSIFICATION_FAILED "
                            f"ticket={ticket.ticket_number} error={exc}"
                        )
"""

if target not in text:
    print("ERROR: Could not locate WhatsApp ticket creation block")
    sys.exit(1)

text = text.replace(target, classification_block, 1)

FILE.write_text(text, encoding="utf-8")

# ------------------------------------------------------------------
# Validate
# ------------------------------------------------------------------

try:
    py_compile.compile(str(FILE), doraise=True)
    print("SUCCESS: whatsapp_service.py compiles")
except Exception as exc:
    print(f"COMPILE FAILED: {exc}")
    shutil.copy2(backup, FILE)
    print("Original restored")
    sys.exit(1)

print("Patch applied successfully")
print("Next steps:")
print("  git diff app/services/whatsapp_service.py")
print("  python -m py_compile app/services/whatsapp_service.py")
print("  git add app/services/whatsapp_service.py")
print('  git commit -m "Add AI classification for WhatsApp tickets"')
print("  git push")