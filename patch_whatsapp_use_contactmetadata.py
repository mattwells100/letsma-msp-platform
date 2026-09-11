from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys

FILE = Path("app/services/whatsapp_service.py")

if not FILE.exists():
    print("ERROR: whatsapp_service.py not found")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

backup = Path(
    str(FILE) + f".bak-contactmetadata-{stamp}"
)

shutil.copy2(FILE, backup)

print(f"Backup created: {backup}")

text = FILE.read_text(encoding="utf-8")

# --------------------------------------------------
# Add ContactMetadata import
# --------------------------------------------------

if "ContactMetadata" not in text:

    old_import = (
        "from app.models import "
    )

    idx = text.find(old_import)

    if idx != -1:
        line_end = text.find("\n", idx)

        current = text[idx:line_end]

        if "ContactMetadata" not in current:
            text = text.replace(
                current,
                current.rstrip() + ", ContactMetadata"
            )
            print("Added ContactMetadata import")

# --------------------------------------------------
# Inject lookup block
# --------------------------------------------------

marker = """
    target = _normalise_number(wa_number)
"""

if marker not in text:
    print("Could not locate lookup marker")
    shutil.copy2(backup, FILE)
    sys.exit(1)

lookup_block = '''

    # --------------------------------------------------
    # ContactMetadata exact match
    # --------------------------------------------------

    metadata = (
        db.query(ContactMetadata)
        .filter(
            ContactMetadata.whatsapp_number == target
        )
        .first()
    )

    if metadata and metadata.contact:
        return (
            metadata.contact.customer,
            metadata.contact,
        )

'''

if "ContactMetadata.whatsapp_number == target" not in text:
    text = text.replace(
        marker,
        marker + lookup_block,
        1
    )

    print("Added ContactMetadata lookup")

FILE.write_text(text, encoding="utf-8")

try:

    py_compile.compile(
        str(FILE),
        doraise=True
    )

    print("Compile OK")

except Exception as exc:

    print(exc)

    shutil.copy2(
        backup,
        FILE
    )

    print("Rollback complete")

    sys.exit(1)

print()
print("SUCCESS")
print()
print("Validate:")
print("python -m py_compile app/services/whatsapp_service.py")
print("python -c \"import app.main; print('IMPORT OK')\"")