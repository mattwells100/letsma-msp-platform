# patch_email_internal_sender_filter.py

from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys

FILE = Path("app/services/email_ingestion_service.py")

if not FILE.exists():
    print("email_ingestion_service.py not found")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

backup = Path(
    str(FILE) + f".bak-internal-filter-{stamp}"
)

shutil.copy2(FILE, backup)

print(f"Backup created: {backup}")

text = FILE.read_text(encoding="utf-8")

if "skipped_internal_sender" in text:
    print("Filter already exists")
    sys.exit(0)

marker = """
        effective_body = _strip_html(body_content) if body_content_type == "html" else body_content
        was_forward = False
"""

if marker not in text:
    print("Insertion point not found")
    shutil.copy2(backup, FILE)
    sys.exit(1)

patch = marker + """

    # -------------------------------------------------
    # Internal Letsma sender protection
    # -------------------------------------------------

    INTERNAL_DOMAINS = {
        "letsma.co.uk",
    }

    domain = ""

    if "@" in effective_email:
        domain = effective_email.split("@")[-1].lower()

    if domain in INTERNAL_DOMAINS:

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
            "action": "skipped_internal_sender",
            "sender": effective_email,
        }

"""

text = text.replace(marker, patch, 1)

FILE.write_text(text, encoding="utf-8")

try:
    py_compile.compile(
        str(FILE),
        doraise=True
    )

    print("Compile OK")

except Exception as exc:

    print(exc)

    shutil.copy2(backup, FILE)

    print("Rollback complete")

    sys.exit(1)

print()
print("SUCCESS")
print()
print("Validate:")
print("python -m py_compile app/services/email_ingestion_service.py")
print('python -c "import app.main; print(\\"IMPORT OK\\")"')