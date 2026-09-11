"""
app/routers/contacts_sync.py

API endpoints to trigger a contact sync from Microsoft Graph for a given
customer, and to reset (delete) previously-synced contacts so a clean
re-sync can repopulate them correctly - e.g. after fixing the guest-user
exclusion logic, this lets you remove contacts that were synced before
the fix without needing direct database access.
"""
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services import graph_service

router = APIRouter(prefix="/api/contacts", tags=["Contacts - M365 Sync"])


@router.post("/sync/{customer_id}")
async def sync_contacts(customer_id: str, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    try:
        result = await graph_service.sync_contacts_for_customer(db, customer)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Microsoft Graph contact sync failed: {e}")
    return result


@router.delete("/synced/{customer_id}")
def reset_synced_contacts(customer_id: str, db: Session = Depends(get_db)):
    """
    Deletes all previously Graph-synced contacts (source='graph_sync') for
    a customer, WITHOUT touching any manually-added contacts. Use this
    once after fixing sync logic (e.g. excluding guest users) to clear out
    contacts that were synced under the old, less-strict rules - then
    click "Sync Contacts" again to repopulate cleanly.
    """
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")

    deleted_count = (
        db.query(models.Contact)
        .filter_by(customer_id=customer_id, source="graph_sync")
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "customer": customer.name, "deleted_contacts": deleted_count}



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

