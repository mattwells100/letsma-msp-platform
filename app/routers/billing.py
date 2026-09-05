from datetime import datetime
from app.services.billing_service import (
generate_monthly_invoice_for_customer, generate_monthly_invoices_for_all_customers,
    )

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


from datetime import datetime
from fastapi import Query


@router.post("/generate-monthly-invoices")
def generate_monthly_invoices(year: int = Query(...), month: int = Query(...), db=Depends(get_db)):
    """
    Generates one consolidated invoice per active customer for the given
    calendar month (contract fee OR PAYG labour, + assigned Amazon
    orders, + license costs). Safe to re-run: already-billed customers
    for that exact month are automatically skipped, never double-billed.
    """
    period_start = datetime(year, month, 1)
    period_end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    results = generate_monthly_invoices_for_all_customers(db, period_start, period_end)
    return {
        "period": f"{period_start.strftime('%B %Y')}",
        "customers_processed": len(results),
        "invoices_created": sum(1 for r in results if r["invoice_created"]),
        "results": results,
    }


@router.delete("/invoices/{invoice_id}")
def delete_invoice(invoice_id: str, db: Session = Depends(get_db)):
    """
    Discard a DRAFT invoice that has NOT been pushed to Xero. Refuses to
    delete anything already synced to Xero (delete/void it in Xero
    instead) so local and Xero records can never silently diverge.
    """
    invoice = db.query(models.Invoice).get(invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.xero_invoice_id:
        raise HTTPException(400, "Invoice already pushed to Xero - cannot discard here.")
    # Unbill any children that reference this invoice so the FK constraints
    # don't block the delete - purchases/time entries return to the unbilled
    # pool rather than being destroyed. (InvoiceLineItems cascade-delete.)
    for order in db.query(models.AmazonOrder).filter_by(invoice_id=invoice.id).all():
        order.invoiced = False
        order.invoice_id = None
    for entry in db.query(models.TimeEntry).filter_by(invoice_id=invoice.id).all():
        entry.invoiced = False
        entry.invoice_id = None
    db.flush()
    db.delete(invoice)
    db.commit()
    return {"status": "ok", "deleted": invoice_id}
