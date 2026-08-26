"""
app/routers/amazon.py  (NEW FILE)

Amazon Business order import and customer-assignment endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.services.amazon_import_service import import_amazon_orders_csv

router = APIRouter(prefix="/api/amazon", tags=["Amazon Orders"])


@router.post("/import")
async def import_orders(file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = (await file.read()).decode("utf-8-sig")  # utf-8-sig strips a BOM if Excel added one on export
    result = import_amazon_orders_csv(db, content)
    if result["errors"]:
        raise HTTPException(400, result["errors"][0])
    return result


@router.get("/unassigned")
def list_unassigned_orders(db: Session = Depends(get_db)):
    orders = db.query(models.AmazonOrder).filter_by(customer_id=None).order_by(models.AmazonOrder.order_date.desc()).all()
    return [
        {
            "id": o.id, "amazon_order_id": o.amazon_order_id, "order_date": o.order_date,
            "total": o.total, "description": o.description,
        }
        for o in orders
    ]


@router.post("/{order_id}/assign")
def assign_order_to_customer(order_id: str, customer_id: str, db: Session = Depends(get_db)):
    order = db.query(models.AmazonOrder).get(order_id)
    if not order:
        raise HTTPException(404, "Amazon order not found")
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    order.customer_id = customer_id
    db.commit()
    return {"ok": True, "order_id": order.amazon_order_id, "assigned_to": customer.name}
