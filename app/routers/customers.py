from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional

from app.database import get_db
from app import models, schemas

router = APIRouter(prefix="/api/customers", tags=["Customers"])


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

