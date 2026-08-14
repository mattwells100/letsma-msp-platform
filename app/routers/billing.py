from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.services import xero_service

router = APIRouter(prefix="/api/billing", tags=["Billing"])


@router.get("/invoices", response_model=List[schemas.InvoiceOut])
def list_invoices(db: Session = Depends(get_db)):
    return db.query(models.Invoice).order_by(models.Invoice.created_at.desc()).all()


@router.post("/invoices", response_model=schemas.InvoiceOut)
async def create_invoice(payload: schemas.InvoiceCreate, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(payload.customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")

    subtotal = sum(li.quantity * li.unit_price for li in payload.line_items)
    invoice = models.Invoice(
        customer_id=payload.customer_id,
        currency=payload.currency,
        due_date=payload.due_date,
        subtotal=subtotal,
        tax_total=round(subtotal * 0.20, 2),   # UK standard VAT assumption; adjust per line TaxType in Xero
        total=round(subtotal * 1.20, 2),
    )
    db.add(invoice)
    db.flush()  # get invoice.id before adding line items

    for li in payload.line_items:
        db.add(models.InvoiceLineItem(invoice_id=invoice.id, **li.model_dump()))

    db.commit()
    db.refresh(invoice)

    if payload.push_to_xero:
        try:
            await xero_service.create_invoice_in_xero(db, invoice, customer)
            db.refresh(invoice)
        except Exception as e:
            # Invoice remains in Draft locally; surface the Xero error without failing the whole request
            raise HTTPException(502, f"Invoice saved locally, but Xero push failed: {e}")

    return invoice


@router.post("/invoices/{invoice_id}/push-to-xero", response_model=schemas.InvoiceOut)
async def push_invoice_to_xero(invoice_id: str, db: Session = Depends(get_db)):
    invoice = db.query(models.Invoice).get(invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.xero_invoice_id:
        raise HTTPException(400, "Invoice has already been pushed to Xero")

    customer = db.query(models.Customer).get(invoice.customer_id)
    try:
        await xero_service.create_invoice_in_xero(db, invoice, customer)
    except Exception as e:
        raise HTTPException(502, f"Xero push failed: {e}")

    db.refresh(invoice)
    return invoice


@router.get("/invoices/{invoice_id}", response_model=schemas.InvoiceOut)
def get_invoice(invoice_id: str, db: Session = Depends(get_db)):
    invoice = db.query(models.Invoice).get(invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    return invoice
