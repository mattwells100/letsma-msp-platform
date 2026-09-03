"""
app/routers/purchasing_email_ingestion.py

Endpoints to manually trigger a purchasing-mailbox poll (orders@letsma.co.uk)
and to confirm a needs_review purchase draft into the normal billable
Unbilled Purchases pipeline. Mirrors app/routers/email_ingestion.py.

VAT convention: identical to app/routers/purchases.py - every price field
here (total, unit_price) is ALWAYS excluding VAT.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services import purchase_email_ingestion_service

router = APIRouter(prefix="/api/purchasing/email-ingestion", tags=["Purchasing-Email-Ingest"])


@router.post("/poll")
async def poll_orders_inbox(db: Session = Depends(get_db)):
    """Manually trigger a check of the orders mailbox for new supplier order
    emails. This same function is also called automatically on a schedule -
    see app/scheduler.py."""
    try:
        result = await purchase_email_ingestion_service.poll_and_process_orders_inbox(db)
    except Exception as e:
        raise HTTPException(502, f"Failed to poll orders mailbox: {e}")
    return result


@router.get("/needs-review")
def list_needs_review(db: Session = Depends(get_db)):
    """Lists all email-ingested orders awaiting human confirmation, oldest first."""
    rows = (
        db.query(models.AmazonOrder)
        .filter(models.AmazonOrder.source == "email_auto")
        .filter(models.AmazonOrder.extraction_status.in_(["needs_review", "failed"]))
        .order_by(models.AmazonOrder.ingested_at.asc())
        .all()
    )
    result = []
    for r in rows:
        primary = r.line_items[0] if r.line_items else None
        result.append({
            "id": r.id,
            "supplier": r.supplier,
            "order_reference": r.amazon_order_id,
            "customer_id": r.customer_id,
            "end_user_hint": r.end_user_hint,
            "description": r.description,
            "quantity": primary.quantity if primary else 1.0,
            "unit_price": primary.unit_price if primary else r.total,  # excluding VAT
            "other_line_items_count": max(len(r.line_items) - 1, 0),
            "total": r.total,  # excluding VAT
            "currency": r.currency,
            "extraction_status": r.extraction_status,
            "ingested_at": r.ingested_at.isoformat() if r.ingested_at else None,
        })
    return result


class ConfirmOrderRequest(BaseModel):
    customer_id: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None  # cost price PER UNIT, EXCLUDING VAT
    total_override: Optional[float] = None  # deprecated - prefer quantity + unit_price; still supported for direct override


@router.post("/{order_id}/confirm")
def confirm_order(order_id: str, payload: ConfirmOrderRequest, db: Session = Depends(get_db)):
    """
    Human confirms a needs_review email-ingested order, optionally
    correcting the customer, description, quantity, or unit price (always
    excluding VAT) in the same action the AI extraction may have gotten
    wrong. Only edits the PRIMARY (first) line item - additional line
    items from a multi-item extraction (e.g. a delivery charge) are left
    untouched and their total is preserved in order.total.
    """
    order = db.query(models.AmazonOrder).filter(models.AmazonOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if payload.customer_id:
        order.customer_id = payload.customer_id
    if payload.description is not None:
        order.description = payload.description

    if payload.quantity is not None or payload.unit_price is not None:
        line_items = list(order.line_items)
        primary = line_items[0] if line_items else None
        other_items_total = sum(li.quantity * li.unit_price for li in line_items[1:]) if len(line_items) > 1 else 0.0

        new_quantity = payload.quantity if payload.quantity is not None else (primary.quantity if primary else 1.0)
        new_unit_price = payload.unit_price if payload.unit_price is not None else (primary.unit_price if primary else order.total)

        if primary:
            primary.quantity = new_quantity
            primary.unit_price = new_unit_price
            if payload.description is not None:
                primary.description = payload.description
        else:
            db.add(models.AmazonOrderLineItem(
                order_id=order.id,
                description=payload.description or order.description or "Item",
                quantity=new_quantity, unit_price=new_unit_price,
            ))

        order.total = round(other_items_total + (new_quantity * new_unit_price), 2)  # excluding VAT
    elif payload.total_override is not None:
        order.total = payload.total_override  # excluding VAT

    if not order.customer_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot confirm an order with no customer assigned - set customer_id first.",
        )

    order.extraction_status = "confirmed"
    db.commit()
    return {"status": "confirmed", "order_id": order.id, "total": order.total}
