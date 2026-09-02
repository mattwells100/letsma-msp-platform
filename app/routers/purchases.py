"""
app/routers/purchases.py

General purchasing module: manually log an order from ANY supplier
(Amazon, CDW, Ingram Micro, a local shop, etc.), assign it to a customer,
and have it billed with markup on their next monthly invoice - reusing
the exact same AmazonOrder table and billing logic already used for
Amazon CSV imports (see app/services/amazon_import_service.py for the
CSV-import path, which remains unchanged and unaffected by this module).
"""
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models

router = APIRouter(prefix="/api/purchases", tags=["Purchasing"])


class PurchaseCreate(BaseModel):
    supplier: str  # e.g. "CDW", "Ingram Micro", "Amazon", "Local Shop"
    description: str
    total: float  # cost price, as paid to the supplier
    order_reference: Optional[str] = None  # supplier's own order/invoice number, if any
    order_date: Optional[datetime] = None
    customer_id: Optional[str] = None  # can assign now, or leave unassigned and assign later


@router.post("/")
def create_purchase(payload: PurchaseCreate, db: Session = Depends(get_db)):
    if payload.customer_id:
        customer = db.query(models.Customer).get(payload.customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found")

    # Use the supplier-provided reference if given, otherwise generate one -
    # amazon_order_id must be unique, so we can't leave it blank.
    order_ref = payload.order_reference or f"MANUAL-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}"

    existing = db.query(models.AmazonOrder).filter_by(amazon_order_id=order_ref).first()
    if existing:
        raise HTTPException(400, f"An order with reference '{order_ref}' already exists")

    order = models.AmazonOrder(
        amazon_order_id=order_ref,
        customer_id=payload.customer_id,
        supplier=payload.supplier,
        order_date=payload.order_date or datetime.utcnow(),
        total=payload.total,
        description=payload.description,
        source="manual",
    )
    db.add(order)
    db.flush()
    db.add(models.AmazonOrderLineItem(
        order_id=order.id, description=payload.description, quantity=1, unit_price=payload.total,
    ))
    db.commit()
    db.refresh(order)

    return {
        "id": order.id, "order_reference": order.amazon_order_id, "supplier": order.supplier,
        "total": order.total, "customer_id": order.customer_id, "assigned": bool(order.customer_id),
    }


@router.get("/")
def list_purchases(customer_id: Optional[str] = None, unassigned_only: bool = False, db: Session = Depends(get_db)):
    query = db.query(models.AmazonOrder)
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    if unassigned_only:
        query = query.filter_by(customer_id=None)
    orders = query.order_by(models.AmazonOrder.order_date.desc()).all()
    return [
        {
            "id": o.id, "order_reference": o.amazon_order_id, "supplier": o.supplier,
            "description": o.description, "total": o.total, "order_date": o.order_date,
            "customer_id": o.customer_id, "invoiced": o.invoiced, "source": o.source,
        }
        for o in orders
    ]


@router.post("/{order_id}/assign")
def assign_purchase_to_customer(order_id: str, customer_id: str, db: Session = Depends(get_db)):
    order = db.query(models.AmazonOrder).get(order_id)
    if not order:
        raise HTTPException(404, "Purchase order not found")
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    order.customer_id = customer_id
    db.commit()
    return {"ok": True, "order_reference": order.amazon_order_id, "assigned_to": customer.name}


@router.delete("/{order_id}")
def delete_purchase(order_id: str, db: Session = Depends(get_db)):
    order = db.query(models.AmazonOrder).get(order_id)
    if not order:
        raise HTTPException(404, "Purchase order not found")
    if order.invoiced:
        raise HTTPException(400, "Cannot delete a purchase that has already been invoiced")
    db.delete(order)
    db.commit()
    return {"ok": True}
