import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app import models, schemas
from app.deps import require_manager_or_admin
from app.services import vuzion_cloudblue_service

router = APIRouter(prefix="/api/customers", tags=["Customers"])


class CloudBlueCustomerLink(BaseModel):
    cloudblue_customer_id: str


class CloudBlueLicenseChangeRequest(BaseModel):
    action: str
    mpn: str
    quantity: int = 1
    subscription_id: str | None = None
    ticket_id: str | None = None


def _normalise_cloudblue_subscriptions(payload: dict | list) -> list[dict]:
    records = payload if isinstance(payload, list) else (payload.get("data") or payload.get("subscriptions") or [])
    if isinstance(records, dict):
        records = records.get("items") or records.get("results") or records.get("subscriptions") or []
    normalised = []
    for subscription in records:
        if not isinstance(subscription, dict):
            continue
        subscription_id = _first_nested_value(subscription, ("id", "subscriptionId", "subscription_id"))
        product = _find_product_record(subscription)
        mpn = _first_nested_value(subscription, ("mpn", "partNumber", "sku", "skuPartNumber", "productMpn", "code"))
        if not mpn or not subscription_id:
            continue
        label = _first_nested_value(product or subscription, ("name", "productName", "friendlyName", "planName")) or mpn
        normalised.append({"id": str(subscription_id), "mpn": str(mpn), "label": str(label)})
    return normalised


def _subscription_plan_id(subscription: dict) -> str | None:
    return _first_nested_value(
        subscription,
        ("planId", "plan_id", "servicePlanId", "service_plan_id", "planCode"),
    )


def _first_nested_value(value: object, keys: tuple[str, ...]) -> object | None:
    if isinstance(value, dict):
        for key in keys:
            if value.get(key) not in (None, ""):
                return value[key]
        for child in value.values():
            found = _first_nested_value(child, keys)
            if found not in (None, ""):
                return found
    elif isinstance(value, list):
        for child in value:
            found = _first_nested_value(child, keys)
            if found not in (None, ""):
                return found
    return None


def _find_product_record(subscription: dict) -> dict | None:
    if any(key in subscription for key in ("mpn", "partNumber", "sku", "skuPartNumber", "productMpn", "code")):
        return subscription
    for key in ("products", "items", "product", "plan", "servicePlan"):
        value = subscription.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
    return None


@router.get("/cloudblue")
async def list_cloudblue_customers():
    """Return CloudBlue customers available to link to local records."""
    try:
        return await vuzion_cloudblue_service.get_customers()
    except vuzion_cloudblue_service.VuzionCloudBlueNotConfigured as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"CloudBlue customer lookup failed: {exc}")


@router.get("/cloudblue/products")
async def list_cloudblue_products():
    """Return products available for an approved licence change."""
    try:
        return await vuzion_cloudblue_service.get_products()
    except Exception as exc:
        raise HTTPException(502, f"CloudBlue product lookup failed: {exc}")


@router.get("/cloudblue/subscriptions/{customer_id}")
async def list_cloudblue_subscriptions(customer_id: str, db: Session = Depends(get_db)):
    """Return active CloudBlue subscriptions for a linked local customer."""
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    if not customer.cloudblue_customer_id:
        raise HTTPException(409, "Customer is not linked to CloudBlue")
    try:
        payload = await vuzion_cloudblue_service.get_subscriptions(customer.cloudblue_customer_id)
        raw_records = payload if isinstance(payload, list) else (payload.get("data") or payload.get("subscriptions") or [])
        if isinstance(raw_records, dict):
            raw_records = raw_records.get("items") or raw_records.get("results") or raw_records.get("subscriptions") or []
        normalised = _normalise_cloudblue_subscriptions(payload)
        if not normalised:
            records = raw_records if isinstance(raw_records, list) else []
            for subscription in records:
                if not isinstance(subscription, dict):
                    continue
                plan_id = _subscription_plan_id(subscription)
                subscription_id = _first_nested_value(subscription, ("id", "subscriptionId", "subscription_id"))
                if not plan_id or not subscription_id:
                    continue
                try:
                    plan = await vuzion_cloudblue_service.get_service_plan(str(plan_id))
                except Exception:
                    continue
                plan_payload = plan.get("data") if isinstance(plan, dict) and isinstance(plan.get("data"), dict) else plan
                mpn = _first_nested_value(plan_payload, ("mpn", "partNumber", "sku", "skuPartNumber", "productMpn", "code"))
                label = _first_nested_value(plan_payload, ("name", "productName", "friendlyName", "planName")) or mpn
                if mpn:
                    normalised.append({"id": str(subscription_id), "mpn": str(mpn), "label": str(label or mpn)})
        return {"data": normalised, "raw_count": len(raw_records) if isinstance(raw_records, list) else 0}
    except Exception as exc:
        raise HTTPException(502, f"CloudBlue subscription lookup failed: {exc}")


@router.get("/", response_model=List[schemas.CustomerOut])
def list_customers(db: Session = Depends(get_db)):
    return db.query(models.Customer).order_by(models.Customer.name).all()


@router.post("/", response_model=schemas.CustomerOut)
def create_customer(payload: schemas.CustomerCreate, db: Session = Depends(get_db)):
    customer = models.Customer(**payload.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=schemas.CustomerOut)
def get_customer(customer_id: str, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    return customer


@router.patch("/{customer_id}/cloudblue-link", response_model=schemas.CustomerOut)
def link_cloudblue_customer(
    customer_id: str,
    payload: CloudBlueCustomerLink,
    db: Session = Depends(get_db),
):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    customer.cloudblue_customer_id = payload.cloudblue_customer_id.strip()
    if not customer.cloudblue_customer_id:
        raise HTTPException(400, "CloudBlue customer ID is required")
    db.commit()
    db.refresh(customer)
    return customer


@router.post("/{customer_id}/cloudblue-license-changes")
async def request_cloudblue_license_change(
    customer_id: str,
    payload: CloudBlueLicenseChangeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    if not customer.cloudblue_customer_id:
        raise HTTPException(409, "Link the customer to CloudBlue before requesting a licence change")
    if payload.action not in {"add", "remove"}:
        raise HTTPException(400, "Action must be add or remove")
    if payload.quantity < 1:
        raise HTTPException(400, "Quantity must be at least 1")
    if not payload.subscription_id:
        raise HTTPException(400, "Select a subscribed licence first")
    try:
        subscriptions = await vuzion_cloudblue_service.get_subscriptions(customer.cloudblue_customer_id)
    except Exception as exc:
        raise HTTPException(502, f"CloudBlue subscription lookup failed: {exc}")
    records = _normalise_cloudblue_subscriptions(subscriptions)
    valid_selection = False
    for subscription in records:
        subscription_id = str(subscription.get("id") or "")
        if subscription_id != payload.subscription_id:
            continue
        valid_selection = subscription.get("mpn") == payload.mpn.strip()
        break
    if not valid_selection:
        raise HTTPException(400, "Selected licence is not on this customer's active CloudBlue subscription")

    change = models.CloudBlueLicenseChange(
        customer_id=customer_id,
        ticket_id=payload.ticket_id,
        action=payload.action,
        mpn=payload.mpn.strip(),
        quantity=payload.quantity,
        subscription_id=payload.subscription_id,
        requested_by=(request.session.get("user") or {}).get("email"),
    )
    db.add(change)
    db.commit()
    db.refresh(change)
    return {"id": change.id, "status": change.status, "customer_id": customer_id}


@router.post("/{customer_id}/cloudblue-license-changes/{change_id}/estimate")
async def estimate_cloudblue_license_change(customer_id: str, change_id: str, db: Session = Depends(get_db)):
    change = db.query(models.CloudBlueLicenseChange).filter_by(id=change_id, customer_id=customer_id).first()
    if not change:
        raise HTTPException(404, "Licence change not found")
    if change.status not in {"pending_approval", "estimated"}:
        raise HTTPException(409, "Only pending changes can be estimated")
    payload = {
        "customerId": change.customer.cloudblue_customer_id,
        "type": "change" if change.action == "remove" else "new",
        "products": [{"mpn": change.mpn, "quantity": change.quantity}],
    }
    change.estimate_payload = json.dumps(payload)
    try:
        result = await vuzion_cloudblue_service.estimate_sales_order(payload)
    except Exception as exc:
        change.status = "estimate_failed"
        db.commit()
        raise HTTPException(502, f"CloudBlue estimate failed: {exc}")
    change.estimate_response = json.dumps(result)
    change.status = "estimated"
    db.commit()
    return {"id": change.id, "status": change.status, "estimate": result}


@router.post("/{customer_id}/cloudblue-license-changes/{change_id}/approve")
async def approve_cloudblue_license_change(
    customer_id: str,
    change_id: str,
    request: Request,
    db: Session = Depends(get_db),
    _=Depends(require_manager_or_admin),
):
    change = db.query(models.CloudBlueLicenseChange).filter_by(id=change_id, customer_id=customer_id).first()
    if not change:
        raise HTTPException(404, "Licence change not found")
    if change.status != "estimated":
        raise HTTPException(409, "Estimate the licence change before approving it")
    payload = {
        "customerId": change.customer.cloudblue_customer_id,
        "type": "change" if change.action == "remove" else "new",
        "products": [{"mpn": change.mpn, "quantity": change.quantity}],
    }
    if change.subscription_id:
        payload["products"][0]["subscriptionId"] = change.subscription_id
    change.status = "approved"
    change.approved_by = (request.session.get("user") or {}).get("email")
    change.approved_at = datetime.utcnow()
    try:
        result = await vuzion_cloudblue_service.place_sales_order(payload)
    except Exception as exc:
        change.status = "order_failed"
        db.commit()
        raise HTTPException(502, f"CloudBlue order failed: {exc}")
    change.order_response = json.dumps(result)
    change.status = "submitted"
    change.completed_at = datetime.utcnow()
    db.commit()
    return {"id": change.id, "status": change.status, "order": result}


@router.put("/{customer_id}", response_model=schemas.CustomerOut)
def update_customer(customer_id: str, payload: schemas.CustomerCreate, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    for k, v in payload.model_dump().items():
        setattr(customer, k, v)
    db.commit()
    db.refresh(customer)
    return customer


@router.delete("/{customer_id}")
def delete_customer(customer_id: str, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    db.delete(customer)
    db.commit()
    return {"ok": True}


@router.post("/{customer_id}/contacts", response_model=schemas.ContactOut)
def add_contact(customer_id: str, payload: schemas.ContactCreate, db: Session = Depends(get_db)):
    payload_dict = payload.model_dump()
    payload_dict["customer_id"] = customer_id
    contact = models.Contact(**payload_dict)
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return contact

def _contact_sort_key(contact):
    """
    Sorts contacts alphabetically by first name. Mirrors the identical
    helper in app/routers/portal.py (kept as a separate local copy here
    rather than importing across router modules, since portal.py's
    version is a private/underscore-prefixed function not meant to be
    imported elsewhere).
    """
    if contact.first_name:
        return contact.first_name.strip().lower()
    if contact.name:
        parts = contact.name.strip().split()
        return parts[0].lower() if parts else ""
    return ""


@router.get("/{customer_id}/contacts", response_model=List[schemas.ContactOut])
def list_customer_contacts(customer_id: str, db: Session = Depends(get_db)):
    """
    Returns a customer's contacts, sorted alphabetically by first name -
    used to populate the "End User" dropdown when creating or editing a
    ticket, so a technician can assign the specific person who reported
    the issue (from either manually-added or M365-synced contacts).
    """
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    return sorted(customer.contacts, key=_contact_sort_key)

