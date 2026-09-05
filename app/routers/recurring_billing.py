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