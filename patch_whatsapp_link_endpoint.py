# patch_whatsapp_link_endpoint.py

from pathlib import Path
from datetime import datetime
import shutil
import py_compile
import sys

ROUTER = Path("app/routers/contacts_sync.py")

if not ROUTER.exists():
    print("ERROR: app/routers/contacts_sync.py not found")
    sys.exit(1)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

backup = Path(
    str(ROUTER) + f".bak-whatsapp-link-{stamp}"
)

shutil.copy2(ROUTER, backup)

print(f"Backup created: {backup}")

text = ROUTER.read_text(encoding="utf-8")

# ------------------------------------------------------------------
# Imports
# ------------------------------------------------------------------

if "from pydantic import BaseModel" not in text:
    text = text.replace(
        "from fastapi import",
        "from pydantic import BaseModel\nfrom fastapi import",
    )

# ------------------------------------------------------------------
# Endpoint
# ------------------------------------------------------------------

if "class WhatsAppLinkRequest" not in text:

    endpoint = '''

class WhatsAppLinkRequest(BaseModel):
    contact_id: str
    whatsapp_number: str


def _normalise_whatsapp(number: str) -> str:
    return "".join(
        ch for ch in (number or "")
        if ch.isdigit()
    )


@router.post("/link-whatsapp")
def link_whatsapp_number(
    payload: WhatsAppLinkRequest,
    db: Session = Depends(get_db),
):
    """
    Permanently link a WhatsApp number to a contact.
    Stored in ContactMetadata so it survives
    Graph contact re-sync operations.
    """

    contact = (
        db.query(models.Contact)
        .filter(
            models.Contact.id == payload.contact_id
        )
        .first()
    )

    if not contact:
        raise HTTPException(
            404,
            "Contact not found"
        )

    normalised = _normalise_whatsapp(
        payload.whatsapp_number
    )

    existing = (
        db.query(models.ContactMetadata)
        .filter(
            models.ContactMetadata.whatsapp_number
            == normalised,
            models.ContactMetadata.contact_id
            != contact.id,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            409,
            "WhatsApp number already linked"
        )

    metadata = (
        db.query(models.ContactMetadata)
        .filter(
            models.ContactMetadata.contact_id
            == contact.id
        )
        .first()
    )

    if metadata is None:

        metadata = models.ContactMetadata(
            contact_id=contact.id,
            graph_user_id=contact.graph_user_id,
        )

        db.add(metadata)

    metadata.whatsapp_number = normalised

    db.commit()
    db.refresh(metadata)

    return {
        "success": True,
        "contact_id": contact.id,
        "contact_name": contact.name,
        "whatsapp_number": metadata.whatsapp_number,
    }

'''

    text += "\n" + endpoint
    print("Added WhatsApp linking endpoint")

ROUTER.write_text(text, encoding="utf-8")

try:
    py_compile.compile(
        str(ROUTER),
        doraise=True,
    )

    print("contacts_sync.py compiled OK")

except Exception as exc:

    print(exc)

    shutil.copy2(
        backup,
        ROUTER,
    )

    print("Original restored")

    sys.exit(1)

print()
print("SUCCESS")
print()
print("Validate:")
print("python -m py_compile app/routers/contacts_sync.py")
print("python -c \"import app.main; print('IMPORT OK')\"")