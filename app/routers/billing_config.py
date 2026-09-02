"""
app/routers/billing_config.py

Lets you configure how each customer is billed (PAYG vs contract, rates,
purchase markup, licence billing mode, licence term commitment) and set
the SELL price (and optional cost price, for profitability reporting)
for each Microsoft 365 licence SKU - as either a MONTHLY or ANNUAL
commitment price (NCE lets you buy a SKU on either term, and annual
commitment usually comes at a discount).

IMPORTANT: monthly and annual prices for the SAME SKU (and same
customer_id scope) are stored as SEPARATE rows, keyed on
(customer_id, sku_part_number, price_term). This means you can
configure both a monthly-commitment price AND a (usually cheaper)
annual-commitment price for the same SKU, and the billing engine will
automatically pick whichever one matches each customer's own
license_term_commitment - falling back to whichever term IS configured
if only one exists, so existing single-price SKUs keep working exactly
as before.

Prices are always stored normalized to a monthly-equivalent
(monthly_unit_price / cost_price) so the billing engine
(billing_service.py) never needs to know or care which term a price was
originally entered as - it always just does seats x monthly_unit_price.
The raw entered figures and their term are kept separately
(entered_sell_price / entered_cost_price / price_term) purely for
display.
"""
from typing import Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models

router = APIRouter(prefix="/api/billing-config", tags=["Billing Configuration"])


def _round2(value: float) -> float:
    return round(value + 1e-9, 2)


class CustomerBillingConfig(BaseModel):
    billing_type: str  # "payg" or "contract"
    monthly_support_fee: Optional[float] = 0.0
    payg_hourly_rate: Optional[float] = 0.0
    amazon_markup_percent: Optional[float] = 0.0  # applied to ALL purchases, any supplier
    license_billing_mode: str = "none"  # "none" | "all" | "selected"
    licensed_skus_billed: Optional[str] = None  # comma-separated SKU list, only used when mode == "selected"
    license_term_commitment: Optional[str] = "monthly"  # "monthly" | "annual" - manually tracked, NOT synced from Graph


@router.put("/customers/{customer_id}")
def set_customer_billing_config(customer_id: str, payload: CustomerBillingConfig, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")

    if payload.billing_type not in ("payg", "contract"):
        raise HTTPException(400, "billing_type must be 'payg' or 'contract'")
    if payload.license_billing_mode not in ("none", "all", "selected"):
        raise HTTPException(400, "license_billing_mode must be 'none', 'all', or 'selected'")
    if payload.license_term_commitment not in ("monthly", "annual"):
        raise HTTPException(400, "license_term_commitment must be 'monthly' or 'annual'")

    customer.billing_type = payload.billing_type
    customer.monthly_support_fee = payload.monthly_support_fee or 0.0
    customer.payg_hourly_rate = payload.payg_hourly_rate or 0.0
    customer.amazon_markup_percent = payload.amazon_markup_percent or 0.0
    customer.license_billing_mode = payload.license_billing_mode
    customer.licensed_skus_billed = payload.licensed_skus_billed
    customer.license_term_commitment = payload.license_term_commitment
    db.commit()
    db.refresh(customer)

    return {
        "customer": customer.name,
        "billing_type": customer.billing_type,
        "monthly_support_fee": customer.monthly_support_fee,
        "payg_hourly_rate": customer.payg_hourly_rate,
        "amazon_markup_percent": customer.amazon_markup_percent,
        "license_billing_mode": customer.license_billing_mode,
        "licensed_skus_billed": customer.licensed_skus_billed,
        "license_term_commitment": customer.license_term_commitment,
    }


@router.get("/customers/{customer_id}")
def get_customer_billing_config(customer_id: str, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    return {
        "customer": customer.name,
        "billing_type": customer.billing_type,
        "monthly_support_fee": customer.monthly_support_fee,
        "payg_hourly_rate": customer.payg_hourly_rate,
        "amazon_markup_percent": customer.amazon_markup_percent,
        "license_billing_mode": customer.license_billing_mode,
        "licensed_skus_billed": customer.licensed_skus_billed,
        "license_term_commitment": customer.license_term_commitment,
    }


@router.get("/customers")
def list_customers_billing_config(db: Session = Depends(get_db)):
    """Quick overview of every customer's billing type + license term
    commitment - useful for answering 'which of my customers are locked
    into annual vs monthly licensing?' at a glance."""
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    return [
        {
            "id": c.id, "name": c.name, "billing_type": c.billing_type,
            "license_term_commitment": c.license_term_commitment or "monthly",
        }
        for c in customers
    ]


class LicensePriceSet(BaseModel):
    sku_part_number: str
    price: float  # the RAW price as entered - interpreted according to price_term below
    price_term: str = "monthly"  # "monthly" | "annual" - which term the `price` figure represents
    cost_price: Optional[float] = 0.0  # the RAW cost as entered - same price_term applies to this too
    customer_id: Optional[str] = None  # omit/null to set the GLOBAL DEFAULT price for this SKU


@router.put("/license-prices")
def set_license_price(payload: LicensePriceSet, db: Session = Depends(get_db)):
    """
    Sets the sell price (and optional cost price) for a licence SKU,
    entered as EITHER a monthly or annual figure (price_term) - either a
    global default (omit customer_id) used for every customer unless
    overridden, or a customer-specific override price.

    Monthly and annual prices for the SAME SKU/customer_id scope are
    stored as SEPARATE rows (upsert is keyed on
    customer_id + sku_part_number + price_term) - this means adding an
    annual price after a monthly price CREATES A SECOND ROW rather than
    overwriting the first, letting you configure both a monthly-term and
    a (usually cheaper) annual-term price for the same SKU.

    The entered figure is normalized to a monthly-equivalent
    (annual / 12) and stored in monthly_unit_price/cost_price, which is
    what the billing engine actually uses.
    """
    if payload.price_term not in ("monthly", "annual"):
        raise HTTPException(400, "price_term must be 'monthly' or 'annual'")

    if payload.customer_id:
        customer = db.query(models.Customer).get(payload.customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found")

    divisor = 12 if payload.price_term == "annual" else 1
    normalized_sell = _round2(payload.price / divisor)
    normalized_cost = _round2((payload.cost_price or 0.0) / divisor)

    existing = db.query(models.LicensePrice).filter_by(
        customer_id=payload.customer_id,
        sku_part_number=payload.sku_part_number,
        price_term=payload.price_term,
    ).first()

    if existing:
        existing.monthly_unit_price = normalized_sell
        existing.cost_price = normalized_cost
        existing.entered_sell_price = payload.price
        existing.entered_cost_price = payload.cost_price or 0.0
    else:
        db.add(models.LicensePrice(
            customer_id=payload.customer_id,
            sku_part_number=payload.sku_part_number,
            monthly_unit_price=normalized_sell,
            cost_price=normalized_cost,
            price_term=payload.price_term,
            entered_sell_price=payload.price,
            entered_cost_price=payload.cost_price or 0.0,
        ))
    db.commit()

    scope = f"customer {payload.customer_id}" if payload.customer_id else "GLOBAL DEFAULT"
    return {
        "ok": True, "sku_part_number": payload.sku_part_number, "scope": scope,
        "price_term": payload.price_term,
        "entered_price": payload.price, "entered_cost_price": payload.cost_price or 0.0,
        "monthly_unit_price": normalized_sell, "cost_price": normalized_cost,
    }


@router.get("/license-prices")
def list_license_prices(db: Session = Depends(get_db)):
    prices = db.query(models.LicensePrice).all()
    return [
        {
            "id": p.id, "sku_part_number": p.sku_part_number,
            "price_term": p.price_term or "monthly",
            "entered_sell_price": p.entered_sell_price if p.entered_sell_price is not None else p.monthly_unit_price,
            "entered_cost_price": p.entered_cost_price if p.entered_cost_price is not None else (p.cost_price or 0.0),
            "monthly_unit_price": p.monthly_unit_price,
            "cost_price": p.cost_price or 0.0,
            "margin": _round2((p.monthly_unit_price or 0) - (p.cost_price or 0.0)),
            "customer_id": p.customer_id, "scope": "customer-specific" if p.customer_id else "global default",
        }
        for p in prices
    ]


@router.delete("/license-prices/{price_id}")
def delete_license_price(price_id: str, db: Session = Depends(get_db)):
    """
    Removes a license price row entirely. Since monthly and annual prices
    for the same SKU are now separate rows, deleting one term's price
    leaves the other term's price (if configured) untouched.
    """
    price = db.query(models.LicensePrice).get(price_id)
    if not price:
        raise HTTPException(404, "Price not found")
    db.delete(price)
    db.commit()
    return {"ok": True, "deleted_id": price_id}


def _get_effective_price_row(db: Session, customer, sku_part_number: str):
    """
    Finds the best-matching LicensePrice row for a customer + SKU,
    preferring a price entered in the SAME commitment term as the
    customer's own license_term_commitment - since annual-commitment
    pricing is typically discounted vs monthly, these are genuinely
    different amounts, not just different display formats of the same
    price. Priority order:
      1. Customer-specific override, matching the customer's term
      2. Customer-specific override, the OTHER term (better than nothing)
      3. Global default, matching the customer's term
      4. Global default, the OTHER term
      5. None (no price configured at all for this SKU)

    This fallback chain means a SKU with only ONE price configured
    (the common case, and all pre-existing data before this feature)
    continues to work exactly as before, regardless of what term any
    given customer is on.
    """
    customer_id = customer.id if customer else None
    term = (getattr(customer, "license_term_commitment", None) if customer else None) or "monthly"
    other_term = "annual" if term == "monthly" else "monthly"

    if customer_id:
        row = db.query(models.LicensePrice).filter_by(
            customer_id=customer_id, sku_part_number=sku_part_number, price_term=term
        ).first()
        if row:
            return row
        row = db.query(models.LicensePrice).filter_by(
            customer_id=customer_id, sku_part_number=sku_part_number, price_term=other_term
        ).first()
        if row:
            return row

    row = db.query(models.LicensePrice).filter_by(
        customer_id=None, sku_part_number=sku_part_number, price_term=term
    ).first()
    if row:
        return row
    return db.query(models.LicensePrice).filter_by(
        customer_id=None, sku_part_number=sku_part_number, price_term=other_term
    ).first()


@router.get("/license-profitability")
def license_profitability(db: Session = Depends(get_db)):
    """
    Reports estimated Microsoft 365 licensing profit: for every currently
    assigned licence seat across all customers, looks up the effective
    sell price and cost price - preferring a price matching that
    customer's own license_term_commitment (monthly/annual), falling
    back to whichever term IS configured if only one exists - and
    returns per-customer, per-SKU seat counts, revenue, cost, and
    margin. SKUs with no price configured at all are reported with a
    null price/margin rather than silently assuming zero cost or zero
    revenue.
    """
    assignments = db.query(models.LicenseAssignment).all()
    customers_map = {c.id: c for c in db.query(models.Customer).all()}

    seat_counts = defaultdict(int)
    friendly_names = {}
    for a in assignments:
        seat_counts[(a.customer_id, a.sku_part_number)] += 1
        friendly_names[a.sku_part_number] = a.friendly_name or a.sku_part_number

    rows = []
    total_revenue = 0.0
    total_cost = 0.0
    total_margin = 0.0
    skus_missing_price = set()

    for (customer_id, sku), seats in seat_counts.items():
        customer_obj = customers_map.get(customer_id)
        customer_name = customer_obj.name if customer_obj else "Unknown"
        term_commitment = (customer_obj.license_term_commitment or "monthly") if customer_obj else "monthly"

        price_row = _get_effective_price_row(db, customer_obj, sku)
        if price_row is None:
            skus_missing_price.add(sku)
            rows.append({
                "customer": customer_name, "sku_part_number": sku,
                "friendly_name": friendly_names.get(sku, sku), "seats": seats,
                "license_term_commitment": term_commitment,
                "sell_price": None, "cost_price": None, "revenue": None, "cost": None, "margin": None,
            })
            continue

        sell = price_row.monthly_unit_price
        cost = price_row.cost_price or 0.0
        revenue = _round2(sell * seats)
        cost_total = _round2(cost * seats)
        margin = _round2(revenue - cost_total)

        total_revenue += revenue
        total_cost += cost_total
        total_margin += margin

        rows.append({
            "customer": customer_name, "sku_part_number": sku,
            "friendly_name": friendly_names.get(sku, sku), "seats": seats,
            "license_term_commitment": term_commitment,
            "sell_price": sell, "cost_price": cost, "revenue": revenue, "cost": cost_total, "margin": margin,
        })

    return {
        "rows": sorted(rows, key=lambda r: (r["customer"], r["sku_part_number"])),
        "totals": {
            "revenue": _round2(total_revenue), "cost": _round2(total_cost), "margin": _round2(total_margin),
        },
        "skus_missing_price_configuration": sorted(skus_missing_price),
    }
