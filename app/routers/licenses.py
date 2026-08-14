from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services import graph_service

router = APIRouter(prefix="/api/licenses", tags=["Microsoft 365 Licensing"])


@router.post("/sync/{customer_id}")
async def sync_licenses(customer_id: str, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    try:
        result = await graph_service.sync_licenses_for_customer(db, customer)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Microsoft Graph sync failed: {e}")
    return result


@router.get("/summary/{customer_id}")
def license_summary(customer_id: str, db: Session = Depends(get_db)):
    rows = db.query(models.TenantLicenseSummary).filter_by(customer_id=customer_id).all()
    return [
        {
            "sku_part_number": r.sku_part_number,
            "friendly_name": r.friendly_name,
            "enabled_units": r.enabled_units,
            "consumed_units": r.consumed_units,
            "available": r.enabled_units - r.consumed_units,
            "last_synced": r.last_synced,
        }
        for r in rows
    ]


@router.get("/assignments/{customer_id}")
def license_assignments(customer_id: str, db: Session = Depends(get_db)):
    rows = db.query(models.LicenseAssignment).filter_by(customer_id=customer_id).all()
    return [
        {
            "user_upn": r.user_upn,
            "display_name": r.display_name,
            "friendly_name": r.friendly_name,
            "sku_part_number": r.sku_part_number,
            "last_synced": r.last_synced,
        }
        for r in rows
    ]
