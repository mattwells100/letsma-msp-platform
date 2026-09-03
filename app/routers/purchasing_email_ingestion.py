"""
app/routers/purchasing_email_ingestion.py

Endpoints to manually trigger a purchasing-mailbox poll (orders@letsma.co.uk)
and to confirm a needs_review AmazonOrder draft into your normal billable
Unbilled Purchases pipeline. Mirrors app/routers/email_ingestion.py.
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
    return [
        {
            "id": r.id,
            "supplier": r.supplier,
            "order_reference": r.amazon_order_id,
            "customer_id": r.customer_id,
            "end_user_hint": r.end_user_hint,
            "total": r.total,
            "currency": r.currency,
            "extraction_status": r.extraction_status,
            "ingested_at": r.ingested_at.isoformat() if r.ingested_at else None,
        }
        for r in rows
    ]


class ConfirmOrderRequest(BaseModel):
    customer_id: Optional[str] = None
    total_override: Optional[float] = None


@router.post("/{order_id}/confirm")
def confirm_order(order_id: str, payload: ConfirmOrderRequest, db: Session = Depends(get_db)):
    """
    Human confirms a needs_review email-ingested order. This doesn't
    change `invoiced` (it's already False, same as any other unbilled
    purchase) - it just flips extraction_status to "confirmed" and
    requires a customer to be assigned, so the order becomes visible/
    trustworthy in your existing Unbilled Purchases view and can be
    added to that customer's next invoice through your normal billing
    flow.
    """
    order = db.query(models.AmazonOrder).filter(models.AmazonOrder.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if payload.customer_id:
        order.customer_id = payload.customer_id
    if payload.total_override is not None:
        order.total = payload.total_override

    if not order.customer_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot confirm an order with no customer assigned - set customer_id first.",
        )

    order.extraction_status = "confirmed"
    db.commit()
    return {"status": "confirmed", "order_id": order.id}
