from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

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
