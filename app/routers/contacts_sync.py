"""
API endpoint to trigger a contact sync from Microsoft Graph for a given
customer.
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