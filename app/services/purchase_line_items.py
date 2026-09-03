"""
app/services/purchase_line_items.py

Shared helper for replacing an AmazonOrder's line items wholesale, used
by both the manual purchases create/edit endpoints (app/routers/
purchases.py) and the email-ingest confirm endpoint (app/routers/
purchasing_email_ingestion.py). This is what enables full multi-line-item
support: an order can have any number of lines (e.g. a laptop + a
delivery charge, or several different products in one supplier email),
and every line is visible and editable in the GUI, not just the first.

Whenever a purchase's line items are edited, we delete ALL existing
AmazonOrderLineItem rows for that order and recreate them from the
submitted list, rather than trying to diff/match old vs new rows by id.
This is simpler and safer given the GUI always fetches the full current
set of line items first (via GET /api/purchases/{id}) before letting the
user edit, so there's no risk of silently losing a row.

VAT convention: every unit_price passed in is EXCLUDING VAT (see
app/routers/purchases.py module docstring) - the recomputed order total
is therefore also excluding VAT.
"""
from typing import List
from sqlalchemy.orm import Session

from app.models import AmazonOrder, AmazonOrderLineItem


def replace_line_items(db: Session, order: AmazonOrder, items: List[dict]) -> float:
    """
    Deletes all existing line items for `order` and recreates them from
    `items` (each a dict with description/quantity/unit_price, all
    excluding VAT). Returns the new order total (excluding VAT) =
    sum(quantity * unit_price) across every line. Does NOT commit - the
    caller is responsible for db.commit().

    Raises ValueError if `items` is empty - an order must always have at
    least one line item.
    """
    if not items:
        raise ValueError("An order must have at least one line item.")

    for existing in list(order.line_items):
        db.delete(existing)
    db.flush()

    total = 0.0
    for item in items:
        quantity = float(item.get("quantity") or 0)
        unit_price = float(item.get("unit_price") or 0)
        description = (item.get("description") or "Item").strip()[:255]
        db.add(AmazonOrderLineItem(
            order_id=order.id, description=description,
            quantity=quantity, unit_price=unit_price,
        ))
        total += quantity * unit_price

    return round(total, 2)
