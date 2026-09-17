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
    records = _cloudblue_collection(payload)
    normalised = []
    for subscription in records:
        if not isinstance(subscription, dict):
            continue
        subscription_id = _first_nested_value(
            subscription,
            ("id", "subscriptionId", "subscription_id", "subscriptionUuid", "subscription_uuid", "subscriptionNumber"),
        )
        product = _find_product_record(subscription)
        mpn = _first_nested_value(
            subscription,
            ("mpn", "partNumber", "part_number", "sku", "skuPartNumber", "sku_part_number",
             "productMpn", "product_mpn", "productCode", "product_code", "offerCode", "offer_code",
             "productNumber", "product_number", "itemCode", "item_code", "code"),
        )
        if not mpn or not subscription_id:
            continue
        label = _first_nested_value(product or subscription, ("name", "productName", "friendlyName", "planName")) or mpn
        normalised.append({"id": str(subscription_id), "mpn": str(mpn), "label": str(label)})
    return normalised


def _subscription_plan_id(subscription: dict) -> str | None:
    plan_id = _first_nested_value(
        subscription,
        ("planId", "plan_id", "servicePlanId", "service_plan_id", "planCode",
         "offerId", "offer_id", "productId", "product_id", "skuId", "sku_id", "itemId", "item_id"),
    )
    if plan_id:
        return str(plan_id)
    for container_name in ("plan", "servicePlan", "offer", "product", "sku", "item"):
        container = subscription.get(container_name) if isinstance(subscription, dict) else None
        if isinstance(container, dict):
            nested_id = _first_nested_value(container, ("id", "planId", "plan_id", "offerId", "offer_id", "productId", "product_id"))
            if nested_id:
                return str(nested_id)
    return None


def _first_nested_value(value: object, keys: tuple[str, ...]) -> object | None:
    if isinstance(value, dict):
        values_by_lower_key = {str(key).lower(): child for key, child in value.items()}
        for key in keys:
            found = values_by_lower_key.get(key.lower())
            if found not in (None, ""):
                return found
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
    product_keys = (
        "mpn", "partNumber", "part_number", "sku", "skuPartNumber", "sku_part_number",
        "productMpn", "product_mpn", "productCode", "product_code", "offerCode", "offer_code",
        "productNumber", "product_number", "itemCode", "item_code", "code",
    )
    if any(str(key).lower() in {item.lower() for item in product_keys} for key in subscription):
        return subscription
    for key in ("products", "items", "product", "plan", "servicePlan"):
        value = subscription.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0]
    return None


async def _normalise_customer_subscriptions(payload: dict | list) -> tuple[list[dict], int]:
    records = _cloudblue_collection(payload)
    normalised = _normalise_cloudblue_subscriptions(payload)
    if normalised or not isinstance(records, list):
        return normalised, len(records) if isinstance(records, list) else 0

    catalogue_payload = None
    if any(isinstance(subscription, dict) and not _first_nested_value(
        subscription,
        ("mpn", "partNumber", "part_number", "sku", "skuPartNumber", "sku_part_number",
         "productMpn", "product_mpn", "productCode", "product_code", "offerCode", "offer_code",
         "productNumber", "product_number", "itemCode", "item_code"),
    ) for subscription in records):
        try:
            catalogue_payload = await vuzion_cloudblue_service.get_products()
        except Exception:
            catalogue_payload = None

    for subscription in records:
        if not isinstance(subscription, dict):
            continue
        plan_id = _subscription_plan_id(subscription)
        subscription_id = _first_nested_value(
            subscription,
            ("id", "subscriptionId", "subscription_id", "subscriptionUuid", "subscription_uuid", "subscriptionNumber"),
        )
        if not subscription_id:
            continue
        plan = None
        if plan_id:
            try:
                plan = await vuzion_cloudblue_service.get_service_plan(str(plan_id))
            except Exception:
                pass
        plan_payload = plan.get("data") if isinstance(plan, dict) and isinstance(plan.get("data"), dict) else plan
        mpn = _first_nested_value(
            plan_payload,
            ("mpn", "partNumber", "part_number", "sku", "skuPartNumber", "sku_part_number",
             "productMpn", "product_mpn", "productCode", "product_code", "offerCode", "offer_code",
             "productNumber", "product_number", "itemCode", "item_code", "code"),
        )
        if not mpn:
            mpn, label = _find_catalogue_product(plan_id, subscription, catalogue_payload)
        else:
            label = _first_nested_value(plan_payload, ("name", "productName", "friendlyName", "planName"))
        label = label or mpn
        if mpn:
            normalised.append({"id": str(subscription_id), "mpn": str(mpn), "label": str(label or mpn)})
    return normalised, len(records)


def _subscription_field_names(records: list) -> list[str]:
    names = set()

    def collect(value: object, prefix: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                names.add(path)
                collect(child, path)
        elif isinstance(value, list):
            for child in value[:3]:
                collect(child, prefix + "[]")

    collect(records)
    return sorted(names)[:100]


def _find_catalogue_product(plan_id: str, subscription: dict, payload: object) -> tuple[object | None, object | None]:
    records = _cloudblue_collection(payload)
    if not isinstance(records, list):
        return None, None
    identifiers = {str(plan_id).lower()} if plan_id else set()
    subscription_name = _first_nested_value(subscription, ("name", "productName", "friendlyName", "planName"))
    for key in ("offerId", "offer_id", "productId", "product_id", "skuId", "sku_id", "itemId", "item_id"):
        value = _first_nested_value(subscription, (key,))
        if value not in (None, ""):
            identifiers.add(str(value).lower())
    for product in records:
        match = _find_catalogue_match(product, identifiers, subscription_name)
        if match:
            return match
    return None, None


def _find_catalogue_match(value: object, identifiers: set[str], subscription_name: object) -> tuple[object, object] | None:
    if isinstance(value, dict):
        product_id = _first_nested_value(value, ("id", "offerId", "offer_id", "productId", "product_id", "skuId", "sku_id", "itemId", "item_id"))
        product_name = _first_nested_value(value, ("name", "productName", "friendlyName", "planName"))
        same_id = product_id is not None and str(product_id).lower() in identifiers
        same_name = subscription_name and product_name and _normalise_text(subscription_name) == _normalise_text(product_name)
        if same_id or same_name:
            mpn = _first_nested_value(value, ("mpn", "partNumber", "part_number", "sku", "skuPartNumber", "sku_part_number", "productCode", "product_code", "offerCode", "offer_code", "productNumber", "product_number", "itemCode", "item_code"))
            label = product_name or subscription_name
            if mpn:
                return mpn, label
        for child in value.values():
            match = _find_catalogue_match(child, identifiers, subscription_name)
            if match:
                return match
    elif isinstance(value, list):
        for child in value:
            match = _find_catalogue_match(child, identifiers, subscription_name)
            if match:
                return match
    return None


def _normalise_text(value: object) -> str:
    return " ".join(str(value).casefold().split())


def _cloudblue_collection(payload: object) -> list:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key, value in payload.items():
        if str(key).lower() in {"data", "items", "results", "subscriptions", "products", "records"}:
            records = _cloudblue_collection(value)
            if records:
                return records
    return []


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
        raw_records = _cloudblue_collection(payload)
        normalised, raw_count = await _normalise_customer_subscriptions(payload)
        response = {"data": normalised, "raw_count": raw_count}
        if raw_count and not normalised:
            response["unresolved_fields"] = _subscription_field_names(raw_records)
        return response
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
    records, _ = await _normalise_customer_subscriptions(subscriptions)
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
    if change.subscription_id:
        payload["products"][0]["subscriptionId"] = change.subscription_id
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

