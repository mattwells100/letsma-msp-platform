"""
app/routers/purchasing_email_ingestion.py

Endpoints to manually trigger a purchasing-mailbox poll (orders@letsma.co.uk)
and to confirm a needs_review purchase draft into the normal billable
Unbilled Purchases pipeline. Mirrors app/routers/email_ingestion.py.

An order can have multiple line items (e.g. a laptop + a delivery charge,
or several different products in one supplier email) - GET /api/purchases/
{id} (defined in purchases.py) returns every line for review, and this
router's /confirm endpoint can replace the FULL set in one action via the
shared app/services/purchase_line_items.py helper, not just edit a single
"primary" line.

VAT convention: identical to app/routers/purchases.py - every price field
here (total, unit_price) is ALWAYS excluding VAT.
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services import purchase_email_ingestion_service
from app.services.purchase_line_items import replace_line_items

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
    """Lists all email-ingested orders awaiting human confirmation, oldest
    first. Line item detail is intentionally NOT included here (only a
    count) - the GUI fetches the full line-item breakdown via
    GET /api/purchases/{id} only when a technician opens the Review modal,
    keeping this summary list lightweight."""
    rows = (
        db.query(models.AmazonOrder)
        .filter(models.AmazonOrder.source == "email_auto")
        .filter(models.AmazonOrder.extraction_status.in_(["needs_review", "failed"]))
        .order_by(models.AmazonOrder.ingested_at.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "supplier": r.supplier,
            "order_reference": r.amazon_order_id,
            "customer_id": r.customer_id,
            "end_user_hint": r.end_user_hint,
            "description": r.description,
            "line_item_count": len(r.line_items),
            "total": r.total,  # excluding VAT
            "currency": r.currency,
            "extraction_status": r.extraction_status,
            "ingested_at": r.ingested_at.isoformat() if r.ingested_at else None,
        }
        for r in rows
    ]


class PurchaseLineItemInput(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float  # cost price PER UNIT, EXCLUDING VAT


class ConfirmOrderRequest(BaseModel):
    customer_id: Optional[str] = None
    supplier: Optional[str] = None
    description: Optional[str] = None
    line_items: Optional[List[PurchaseLineItemInput]] = None  # if provided, REPLACES ALL AI-extracted line items; omit to keep them as extracted


@router.post("/{order_id}/confirm")
def confirm_order(order_id: str, payload: ConfirmOrderRequest, db: Session = Depends(get_db)):
    """
    Human confirms a needs_review email-ingested order, optionally
    correcting the customer, supplier, description, or the FULL set of
    line items (descriptions/quantities/unit prices, always excluding
    VAT) the AI extraction may have gotten wrong. Supports orders with
    any number of lines - if `line_items` is provided it must contain
    every line for the order (the GUI fetches the current full list via
    GET /api/purchases/{id} before letting a technician edit and confirm).
    """
    order = db.query(models.AmazonOrder).filter(models.AmazonOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if payload.customer_id:
        customer = db.query(models.Customer).get(payload.customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found")
        order.customer_id = payload.customer_id

    if payload.supplier is not None:
        order.supplier = payload.supplier
    if payload.description is not None:
        order.description = payload.description

    if payload.line_items is not None:
        try:
            order.total = replace_line_items(db, order, [li.dict() for li in payload.line_items])
        except ValueError as e:
            raise HTTPException(400, str(e))

    if not order.customer_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot confirm an order with no customer assigned - set customer_id first.",
        )

    order.extraction_status = "confirmed"
    db.commit()
    return {"status": "confirmed", "order_id": order.id, "total": order.total}
