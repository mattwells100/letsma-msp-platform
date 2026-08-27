"""
app/routers/billing_config.py

Lets you configure how each customer is billed (PAYG vs contract, rates,
Amazon markup, licence billing mode) and set the monthly price to charge
for each Microsoft 365 licence SKU.
"""
from typing import Optional
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
    amazon_markup_percent: Optional[float] = 0.0
    license_billing_mode: str = "none"  # "none" | "all" | "selected"
    licensed_skus_billed: Optional[str] = None


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
    monthly_unit_price: float
    customer_id: Optional[str] = None


@router.put("/license-prices")
def set_license_price(payload: LicensePriceSet, db: Session = Depends(get_db)):
    if payload.customer_id:
        customer = db.query(models.Customer).get(payload.customer_id)
        if not customer:
            raise HTTPException(404, "Customer not found")

    existing = db.query(models.LicensePrice).filter_by(
        customer_id=payload.customer_id, sku_part_number=payload.sku_part_number
    ).first()

    if existing:
        existing.monthly_unit_price = payload.monthly_unit_price
    else:
        db.add(models.LicensePrice(
            customer_id=payload.customer_id,
            sku_part_number=payload.sku_part_number,
            monthly_unit_price=payload.monthly_unit_price,
        ))
    db.commit()

    scope = f"customer {payload.customer_id}" if payload.customer_id else "GLOBAL DEFAULT"
    return {"ok": True, "sku_part_number": payload.sku_part_number,
            "monthly_unit_price": payload.monthly_unit_price, "scope": scope}


@router.get("/license-prices")
def list_license_prices(db: Session = Depends(get_db)):
    prices = db.query(models.LicensePrice).all()
    return [
        {
            "id": p.id, "sku_part_number": p.sku_part_number, "monthly_unit_price": p.monthly_unit_price,
            "customer_id": p.customer_id, "scope": "customer-specific" if p.customer_id else "global default",
        }
        for p in prices
    ]