from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys

FILE = Path("app/services/whatsapp_service.py")

if not FILE.exists():
    print("ERROR: whatsapp_service.py not found")
    sys.exit(1)

backup = FILE.with_suffix(
    FILE.suffix + f".bak-debug-{datetime.now():%Y%m%d-%H%M%S}"
)
shutil.copy2(FILE, backup)
print(f"Backup created: {backup}")

text = FILE.read_text(encoding="utf-8")

old = """
                    try:
"""

new = """
                    try:
                        print(
                            f"WHATSAPP_CLASSIFICATION_START "
                            f"ticket={ticket.ticket_number}"
                        )
"""

if "WHATSAPP_CLASSIFICATION_START" not in text:
    text = text.replace(old, new, 1)

old2 = """
                        ticket.estimated_minutes = suggestion.get("estimated_minutes")

                    except Exception as exc:
"""

new2 = """
                        ticket.estimated_minutes = suggestion.get("estimated_minutes")

                        print(
                            f"WHATSAPP_CLASSIFICATION_RESULT "
                            f"ticket={ticket.ticket_number} "
                            f"category={ticket.category} "
                            f"subcategory={ticket.subcategory} "
                            f"estimate={ticket.estimated_minutes}"
                        )

                    except Exception as exc:
                        import traceback

                        print(
                            f"WHATSAPP_CLASSIFICATION_FAILED "
                            f"ticket={ticket.ticket_number} "
                            f"error={repr(exc)}"
                        )

                        traceback.print_exc()
"""

if "WHATSAPP_CLASSIFICATION_RESULT" not in text:
    text = text.replace(old2, new2, 1)

FILE.write_text(text, encoding="utf-8")

try:
    py_compile.compile(str(FILE), doraise=True)
    print("SUCCESS: compile passed")
except Exception as exc:
    print(f"COMPILE FAILED: {exc}")
    shutil.copy2(backup, FILE)
    print("Original restored")
    sys.exit(1)

print("Patch applied successfully")