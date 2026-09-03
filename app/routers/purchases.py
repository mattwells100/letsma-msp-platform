"""
app/routers/purchases.py

General purchasing module: manually log an order from ANY supplier
(Amazon, CDW, Ingram Micro, a local shop, etc.), assign it to a customer,
and have it billed with markup on their next monthly invoice - reusing
the exact same AmazonOrder table and billing logic already used for
Amazon CSV imports (see app/services/amazon_import_service.py for the
CSV-import path, which remains unchanged and unaffected by this module).

IMPORTANT - VAT convention used throughout this module and the wider
purchasing module (including email-auto-ingested orders - see
purchase_email_ingestion_service.py): every price stored here
(AmazonOrder.total, AmazonOrderLineItem.unit_price) is ALWAYS the cost
price EXCLUDING VAT. This is what gets marked up (Customer.
amazon_markup_percent) to produce the customer-facing sell price, with
VAT then added separately at invoice time via Xero's tax_type (see
InvoiceLineItem.tax_type = "OUTPUT2" for UK 20% VAT on sales). Never
store an inc-VAT figure in these fields.
"""
from typing import Optional, List
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
    quantity: float = 1.0
    unit_price: float  # cost price PER UNIT, EXCLUDING VAT, as paid to the supplier
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

    total_ex_vat = round(payload.quantity * payload.unit_price, 2)

    order = models.AmazonOrder(
        amazon_order_id=order_ref,
        customer_id=payload.customer_id,
        supplier=payload.supplier,
        order_date=payload.order_date or datetime.utcnow(),
        total=total_ex_vat,  # excluding VAT - see module docstring
        description=payload.description,
        source="manual",
    )
    db.add(order)
    db.flush()
    db.add(models.AmazonOrderLineItem(
        order_id=order.id, description=payload.description,
        quantity=payload.quantity, unit_price=payload.unit_price,
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


@router.get("/{order_id}")
def get_purchase(order_id: str, db: Session = Depends(get_db)):
    """Full detail for a single purchase, including its line items - used
    to pre-fill the Edit modal in the GUI."""
    order = db.query(models.AmazonOrder).get(order_id)
    if not order:
        raise HTTPException(404, "Purchase order not found")

    primary = order.line_items[0] if order.line_items else None
    other_items_total = sum(li.quantity * li.unit_price for li in order.line_items[1:]) if len(order.line_items) > 1 else 0.0

    return {
        "id": order.id,
        "order_reference": order.amazon_order_id,
        "supplier": order.supplier,
        "description": order.description,
        "customer_id": order.customer_id,
        "total": order.total,  # excluding VAT
        "currency": order.currency,
        "invoiced": order.invoiced,
        "source": order.source,
        "order_date": order.order_date,
        "quantity": primary.quantity if primary else 1.0,
        "unit_price": primary.unit_price if primary else order.total,  # excluding VAT, per unit
        "other_line_items_count": max(len(order.line_items) - 1, 0),
        "other_line_items_total": round(other_items_total, 2),
    }


class PurchaseUpdate(BaseModel):
    customer_id: Optional[str] = None  # "" (empty string) explicitly unassigns; omit field entirely to leave unchanged
    supplier: Optional[str] = None
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None  # cost price PER UNIT, EXCLUDING VAT


@router.patch("/{order_id}")
def update_purchase(order_id: str, payload: PurchaseUpdate, db: Session = Depends(get_db)):
    """
    General-purpose edit: correct the assigned customer, supplier,
    description, quantity, or unit price (always excluding VAT) on an
    existing purchase. Refuses to edit anything already invoiced, since
    that would silently change a figure the customer has already been
    billed for.

    Only the PRIMARY (first) line item's quantity/unit_price is edited
    here - if an order has additional line items (e.g. an email-ingested
    multi-item order with a delivery charge as a second item), those are
    left untouched and their total is preserved in order.total.
    """
    order = db.query(models.AmazonOrder).get(order_id)
    if not order:
        raise HTTPException(404, "Purchase order not found")
    if order.invoiced:
        raise HTTPException(400, "Cannot edit a purchase that has already been invoiced")

    if payload.customer_id is not None:
        if payload.customer_id == "":
            order.customer_id = None
        else:
            customer = db.query(models.Customer).get(payload.customer_id)
            if not customer:
                raise HTTPException(404, "Customer not found")
            order.customer_id = payload.customer_id

    if payload.supplier is not None:
        order.supplier = payload.supplier

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

    db.commit()
    db.refresh(order)
    return {
        "id": order.id, "order_reference": order.amazon_order_id, "supplier": order.supplier,
        "description": order.description, "total": order.total, "customer_id": order.customer_id,
    }


@router.post("/{order_id}/assign")
def assign_purchase_to_customer(order_id: str, customer_id: str, db: Session = Depends(get_db)):
    """Kept for backward compatibility - prefer PATCH /{order_id} going
    forward, which can also correct description/quantity/price at the
    same time as reassigning the customer."""
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
