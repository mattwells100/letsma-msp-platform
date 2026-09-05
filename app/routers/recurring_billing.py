from uuid import uuid4
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import RecurringBillingItem

router = APIRouter()


@router.get("/api/customers/{customer_id}/recurring-billing")
def get_recurring_items(
    customer_id: str,
    db: Session = Depends(get_db),
):
    return (
        db.query(RecurringBillingItem)
        .filter(
            RecurringBillingItem.customer_id == customer_id
        )
        .order_by(
            RecurringBillingItem.description
        )
        .all()
    )


@router.post("/api/customers/{customer_id}/recurring-billing")
def create_recurring_item(
    customer_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    item = RecurringBillingItem(
        id=str(uuid4()),
        customer_id=customer_id,
        description=payload["description"],
        quantity=payload["quantity"],
        cost_price=payload["cost_price"],
        sale_price=payload["sale_price"],
        supplier_name=payload.get("supplier_name"),
        billing_frequency=payload["billing_frequency"],
        billing_category=payload["billing_category"],
        start_date=date.fromisoformat(payload["start_date"]),
        next_invoice_date=date.fromisoformat(payload["start_date"]),
        notes=payload.get("notes"),
    )

    db.add(item)
    db.commit()

    return {"status": "ok"}


# ---- Recurring Billing Catalogue (added by apply_catalogue_changes.py) ----
from uuid import uuid4 as _uuid4
from datetime import date as _date
from fastapi import HTTPException as _HTTPException
from app import models as _models


@router.get("/api/recurring-catalog")
def list_catalog(db: Session = Depends(get_db)):
    return (
        db.query(_models.RecurringBillingCatalogItem)
        .order_by(_models.RecurringBillingCatalogItem.name)
        .all()
    )


@router.post("/api/recurring-catalog")
def create_catalog_item(payload: dict, db: Session = Depends(get_db)):
    item = _models.RecurringBillingCatalogItem(
        id=str(_uuid4()),
        name=payload["name"],
        description=payload["description"],
        supplier_name=payload.get("supplier_name"),
        billing_category=payload.get("billing_category", "SERVICE"),
        default_cost_price=payload.get("default_cost_price", 0),
        default_sale_price=payload.get("default_sale_price", 0),
        default_billing_frequency=payload.get("default_billing_frequency", "MONTHLY"),
        notes=payload.get("notes"),
    )
    db.add(item)
    db.commit()
    return {"status": "ok", "id": item.id}


@router.put("/api/recurring-catalog/{item_id}")
def update_catalog_item(item_id: str, payload: dict, db: Session = Depends(get_db)):
    item = db.query(_models.RecurringBillingCatalogItem).get(item_id)
    if not item:
        raise _HTTPException(404, "Catalogue item not found")
    for field in ["name", "description", "supplier_name", "billing_category",
                  "default_cost_price", "default_sale_price",
                  "default_billing_frequency", "is_active", "notes"]:
        if field in payload:
            setattr(item, field, payload[field])
    db.commit()
    return {"status": "ok"}


@router.delete("/api/recurring-catalog/{item_id}")
def delete_catalog_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(_models.RecurringBillingCatalogItem).get(item_id)
    if not item:
        raise _HTTPException(404, "Catalogue item not found")
    item.is_active = False
    db.commit()
    return {"status": "ok"}


@router.post("/api/customers/{customer_id}/recurring-billing/from-catalog")
def add_from_catalog(customer_id: str, payload: dict, db: Session = Depends(get_db)):
    catalog = db.query(_models.RecurringBillingCatalogItem).get(payload["catalog_item_id"])
    if not catalog:
        raise _HTTPException(404, "Catalogue item not found")
    start = _date.fromisoformat(payload["start_date"])
    item = _models.RecurringBillingItem(
        id=str(_uuid4()),
        customer_id=customer_id,
        catalog_item_id=catalog.id,
        description=payload.get("description") or catalog.description,
        supplier_name=payload.get("supplier_name") or catalog.supplier_name,
        billing_category=payload.get("billing_category") or catalog.billing_category,
        quantity=payload.get("quantity", 1),
        cost_price=payload.get("cost_price", catalog.default_cost_price),
        sale_price=payload.get("sale_price", catalog.default_sale_price),
        billing_frequency=payload.get("billing_frequency") or catalog.default_billing_frequency,
        start_date=start,
        next_invoice_date=start,
        notes=payload.get("notes"),
    )
    db.add(item)
    db.commit()
    return {"status": "ok", "id": item.id}
