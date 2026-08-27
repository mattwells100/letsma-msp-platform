"""
app/routers/contacts_sync.py

API endpoints to trigger a contact sync from Microsoft Graph for a given
customer, and to reset (delete) previously-synced contacts so a clean
re-sync can repopulate them correctly - e.g. after fixing the guest-user
exclusion logic, this lets you remove contacts that were synced before
the fix without needing direct database access.
"""
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
