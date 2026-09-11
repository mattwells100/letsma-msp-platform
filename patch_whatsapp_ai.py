from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys

FILE = Path("app/services/whatsapp_service.py")

backup = FILE.with_suffix(
    FILE.suffix + f".bak-ai-{datetime.now():%Y%m%d-%H%M%S}"
)
shutil.copy2(FILE, backup)
print("Backup:", backup)

text = FILE.read_text(encoding="utf-8")

# ------------------------------------------------------------------
# imports
# ------------------------------------------------------------------

extra_imports = """
import asyncio
import json

from app.services import azure_openai_service
from app.routers.teams_bot import (
    AI_TICKET_CATEGORIES,
    _parse_ticket_classification,
)
"""

if "import asyncio" not in text:
    marker = "from datetime import datetime"
    text = text.replace(marker, marker + "\n" + extra_imports)

# ------------------------------------------------------------------
# inject classification
# ------------------------------------------------------------------

old = """
                    db.add(ticket)
                    is_new = True
"""

new = """
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
                            "Use only the supplied ticket evidence.\\n\\n"
                            f"Ticket description:\\n{body}"
                        )

                        raw_result = asyncio.run(
                            azure_openai_service.classify_ticket(
                                prompt,
                                allowed_categories=AI_TICKET_CATEGORIES,
                            )
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

if old not in text:
    print("Could not find insertion point")
    sys.exit(1)

text = text.replace(old, new, 1)

FILE.write_text(text, encoding="utf-8")

try:
    py_compile.compile(str(FILE), doraise=True)
    print("Compile OK")
except Exception as exc:
    print("Compile failed:", exc)
    shutil.copy2(backup, FILE)
    sys.exit(1)

print("Patch successful")