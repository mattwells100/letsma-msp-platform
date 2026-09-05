"""
app/routers/purchases.py

General purchasing module: manually log an order from ANY supplier
(Amazon, CDW, Ingram Micro, a local shop, etc.), assign it to a customer,
and have it billed with markup on their next monthly invoice - reusing
the exact same AmazonOrder table and billing logic already used for
Amazon CSV imports (see app/services/amazon_import_service.py for the
CSV-import path, which remains unchanged and unaffected by this module).

Every order can have MULTIPLE line items (e.g. a laptop + a delivery
charge, or several different products) - the full list is always
returned/editable via GET/PATCH /{order_id}, not just a single "primary"
item. See app/services/purchase_line_items.py for the shared
replace-all-line-items logic used here and in the email-ingest confirm
endpoint.

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
from app.services.purchase_line_items import replace_line_items

router = APIRouter(prefix="/api/purchases", tags=["Purchasing"])


class PurchaseLineItemInput(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float  # cost price PER UNIT, EXCLUDING VAT


class PurchaseCreate(BaseModel):
    supplier: str  # e.g. "CDW", "Ingram Micro", "Amazon", "Local Shop"
    description: Optional[str] = None  # order-level label; defaults to the first line item's description if omitted
    order_reference: Optional[str] = None  # supplier's own order/invoice number, if any
    order_date: Optional[datetime] = None
    customer_id: Optional[str] = None  # can assign now, or leave unassigned and assign later
    line_items: List[PurchaseLineItemInput]


@router.post("/")
def create_purchase(payload: PurchaseCreate, db: Session = Depends(get_db)):
    if not payload.line_items:
        raise HTTPException(400, "At least one line item is required")
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
        total=0.0,  # set below once line items are attached
        description=payload.description or payload.line_items[0].description,
        source="manual",
    )
    db.add(order)
    db.flush()  # populate order.id before attaching line items

    order.total = replace_line_items(db, order, [li.dict() for li in payload.line_items])

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

    result = []
    for o in orders:
        items = o.line_items
        # Only show a single quantity/unit_price figure when there's
        # exactly one line item - for multi-line orders these are left
        # null (the GUI shows an item count badge instead), since a
        # single number can't meaningfully represent several different
        # products/prices. Full breakdown is always available via
        # GET /{order_id}.
        single = items[0] if len(items) == 1 else None
        result.append({
            "id": o.id, "order_reference": o.amazon_order_id, "supplier": o.supplier,
            "description": o.description, "total": o.total, "order_date": o.order_date,
            "customer_id": o.customer_id, "invoiced": o.invoiced, "source": o.source,
            "currency": o.currency,
            "line_item_count": len(items),
            "quantity": single.quantity if single else None,
            "unit_price": single.unit_price if single else None,  # excluding VAT
        })
    return result


@router.get("/{order_id}")
def get_purchase(order_id: str, db: Session = Depends(get_db)):
    """Full detail for a single purchase, including EVERY line item - used
    to pre-fill the Edit/Review modal in the GUI."""
    order = db.query(models.AmazonOrder).get(order_id)
    if not order:
        raise HTTPException(404, "Purchase order not found")

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
        "line_items": [
            {
                "id": li.id, "description": li.description, "quantity": li.quantity,
                "unit_price": li.unit_price,  # excluding VAT
                "line_total": round(li.quantity * li.unit_price, 2),
            }
            for li in order.line_items
        ],
    }


class PurchaseUpdate(BaseModel):
    customer_id: Optional[str] = None  # "" (empty string) explicitly unassigns; omit field entirely to leave unchanged
    supplier: Optional[str] = None
    description: Optional[str] = None
    line_items: Optional[List[PurchaseLineItemInput]] = None  # if provided, REPLACES ALL line items - must include every line, not just the ones changed


@router.patch("/{order_id}")
def update_purchase(order_id: str, payload: PurchaseUpdate, db: Session = Depends(get_db)):
    """
    General-purpose edit: correct the assigned customer, supplier,
    order-level description, or the full set of line items (descriptions,
    quantities, unit prices - always excluding VAT) on an existing
    purchase. Refuses to edit anything already invoiced, since that would
    silently change a figure the customer has already been billed for.

    When `line_items` is provided, it must contain the COMPLETE set of
    lines for the order (the GUI always fetches the current full list via
    GET first, then submits it back with edits applied) - this replaces
    every existing line item, so a partial list would delete lines that
    weren't meant to be removed.
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

    if payload.line_items is not None:
        try:
            order.total = replace_line_items(db, order, [li.dict() for li in payload.line_items])
        except ValueError as e:
            raise HTTPException(400, str(e))

    db.commit()
    db.refresh(order)
    return {
        "id": order.id, "order_reference": order.amazon_order_id, "supplier": order.supplier,
        "description": order.description, "total": order.total, "customer_id": order.customer_id,
    }


@router.post("/{order_id}/assign")
def assign_purchase_to_customer(order_id: str, customer_id: str, db: Session = Depends(get_db)):
    """Kept for backward compatibility - prefer PATCH /{order_id} going
    forward, which can also correct line items at the same time as
    reassigning the customer."""
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
    # Remove the processed-email dedup row(s) that reference this order first,
    # otherwise the FK constraint blocks the delete. (Line items cascade.)
    # Note: clearing the dedup record means the source email can be
    # re-ingested on the next poll - intended for clearing junk rows.
    db.query(models.ProcessedPurchaseEmail).filter_by(order_id=order.id).delete()
    db.flush()
    db.delete(order)
    db.commit()
    return {"ok": True}
