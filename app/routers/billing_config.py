"""
app/routers/billing_config.py

Lets you configure how each customer is billed (PAYG vs contract, rates,
purchase markup, licence billing mode) and set the monthly SELL price
(and optional cost price, for profitability reporting) for each
Microsoft 365 licence SKU.
"""
from typing import Optional
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models

router = APIRouter(prefix="/api/billing-config", tags=["Billing Configuration"])


class CustomerBillingConfig(BaseModel):
    billing_type: str  # "payg" or "contract"
    monthly_support_fee: Optional[float] = 0.0
    payg_hourly_rate: Optional[float] = 0.0
    amazon_markup_percent: Optional[float] = 0.0  # applied to ALL purchases, any supplier
    license_billing_mode: str = "none"  # "none" | "all" | "selected"
    licensed_skus_billed: Optional[str] = None  # comma-separated SKU list, only used when mode == "selected"


@router.put("/customers/{customer_id}")
def set_customer_billing_config(customer_id: str, payload: CustomerBillingConfig, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")

    if payload.billing_type not in ("payg", "contract"):
        raise HTTPException(400, "billing_type must be 'payg' or 'contract'")
    if payload.license_billing_mode not in ("none", "all", "selected"):
        raise HTTPException(400, "license_billing_mode must be 'none', 'all', or 'selected'")

    customer.billing_type = payload.billing_type
    customer.monthly_support_fee = payload.monthly_support_fee or 0.0
    customer.payg_hourly_rate = payload.payg_hourly_rate or 0.0
    customer.amazon_markup_percent = payload.amazon_markup_percent or 0.0
    customer.license_billing_mode = payload.license_billing_mode
    customer.licensed_skus_billed = payload.licensed_skus_billed
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
    }


class LicensePriceSet(BaseModel):
    sku_part_number: str
    monthly_unit_price: float  # what you CHARGE the customer
    cost_price: Optional[float] = 0.0  # what YOU pay (e.g. CSP cost) - never billed, used for profitability only
    customer_id: Optional[str] = None  # omit/null to set the GLOBAL DEFAULT price for this SKU


@router.put("/license-prices")
def set_license_price(payload: LicensePriceSet, db: Session = Depends(get_db)):
    """
    Sets the monthly sell price (and optional cost price) for a licence
    SKU - either a global default (omit customer_id) used for every
    customer unless overridden, or a customer-specific override price.
    Upserts: calling this again for the same (customer_id, sku_part_number)
    pair updates the existing price rather than creating a duplicate row.
    """
    if payload.customer_id:
        customer = db.query(models.Customer).get(payload.customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found")

    existing = db.query(models.LicensePrice).filter_by(
        customer_id=payload.customer_id, sku_part_number=payload.sku_part_number
    ).first()

    if existing:
        existing.monthly_unit_price = payload.monthly_unit_price
        existing.cost_price = payload.cost_price or 0.0
    else:
        db.add(models.LicensePrice(
            customer_id=payload.customer_id,
            sku_part_number=payload.sku_part_number,
            monthly_unit_price=payload.monthly_unit_price,
            cost_price=payload.cost_price or 0.0,
        ))
    db.commit()

    scope = f"customer {payload.customer_id}" if payload.customer_id else "GLOBAL DEFAULT"
    return {"ok": True, "sku_part_number": payload.sku_part_number,
            "monthly_unit_price": payload.monthly_unit_price, "cost_price": payload.cost_price or 0.0, "scope": scope}


@router.get("/license-prices")
def list_license_prices(db: Session = Depends(get_db)):
    prices = db.query(models.LicensePrice).all()
    return [
        {
            "id": p.id, "sku_part_number": p.sku_part_number, "monthly_unit_price": p.monthly_unit_price,
            "cost_price": p.cost_price or 0.0, "margin": _round2(p.monthly_unit_price - (p.cost_price or 0.0)),
            "customer_id": p.customer_id, "scope": "customer-specific" if p.customer_id else "global default",
        }
        for p in prices
    ]


def _round2(value: float) -> float:
    return round(value + 1e-9, 2)


def _get_effective_price_row(db: Session, customer_id: str, sku_part_number: str):
    """Same override logic as billing_service.py: customer-specific row
    wins over the global default row for the same SKU."""
    override = db.query(models.LicensePrice).filter_by(customer_id=customer_id, sku_part_number=sku_part_number).first()
    if override:
        return override
    return db.query(models.LicensePrice).filter_by(customer_id=None, sku_part_number=sku_part_number).first()


@router.get("/license-profitability")
def license_profitability(db: Session = Depends(get_db)):
    """
    Reports estimated Microsoft 365 licensing profit: for every currently
    assigned licence seat across all customers, looks up the effective
    sell price and cost price (customer-specific override if set,
    otherwise the global default), and returns per-customer, per-SKU
    seat counts, revenue, cost, and margin. SKUs with no price configured
    are reported with a null price/margin rather than silently assuming
    zero cost or zero revenue, so gaps in your pricing setup are visible
    rather than hidden.
    """
    assignments = db.query(models.LicenseAssignment).all()
    customers = {c.id: c.name for c in db.query(models.Customer).all()}

    # Group seat counts by (customer_id, sku_part_number)
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
        price_row = _get_effective_price_row(db, customer_id, sku)
        if price_row is None:
            skus_missing_price.add(sku)
            rows.append({
                "customer": customers.get(customer_id, "Unknown"), "sku_part_number": sku,
                "friendly_name": friendly_names.get(sku, sku), "seats": seats,
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
            "customer": customers.get(customer_id, "Unknown"), "sku_part_number": sku,
            "friendly_name": friendly_names.get(sku, sku), "seats": seats,
            "sell_price": sell, "cost_price": cost, "revenue": revenue, "cost": cost_total, "margin": margin,
        })

    return {
        "rows": sorted(rows, key=lambda r: (r["customer"], r["sku_part_number"])),
        "totals": {
            "revenue": _round2(total_revenue), "cost": _round2(total_cost), "margin": _round2(total_margin),
        },
        "skus_missing_price_configuration": sorted(skus_missing_price),
    }
