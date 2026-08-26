"""
app/routers/time_entries.py  (NEW FILE)

Helpdesk labour logging - used to bill PAYG customers monthly based on
actual hours worked. Contract customers can still have time logged for
reporting/visibility, it just doesn't directly drive their invoice total.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from app.database import get_db
from app import models

router = APIRouter(prefix="/api/time-entries", tags=["Time Entries"])


class TimeEntryCreate(BaseModel):
    customer_id: str
    ticket_id: Optional[str] = None
    technician_name: Optional[str] = None
    work_date: Optional[datetime] = None
    hours: float
    description: Optional[str] = None
    billable: bool = True
    hourly_rate_override: Optional[float] = None


@router.post("/")
def create_time_entry(payload: TimeEntryCreate, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(payload.customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    entry = models.TimeEntry(
        customer_id=payload.customer_id,
        ticket_id=payload.ticket_id,
        technician_name=payload.technician_name,
        work_date=payload.work_date or datetime.utcnow(),
        hours=payload.hours,
        description=payload.description,
        billable=payload.billable,
        hourly_rate_override=payload.hourly_rate_override,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": entry.id, "hours": entry.hours, "billable": entry.billable}


@router.get("/")
def list_time_entries(customer_id: Optional[str] = None, unbilled_only: bool = False, db: Session = Depends(get_db)):
    query = db.query(models.TimeEntry)
    if customer_id:
        query = query.filter_by(customer_id=customer_id)
    if unbilled_only:
        query = query.filter_by(invoiced=False)
    entries = query.order_by(models.TimeEntry.work_date.desc()).all()
    return [
        {
            "id": e.id, "customer_id": e.customer_id, "work_date": e.work_date, "hours": e.hours,
            "description": e.description, "billable": e.billable, "invoiced": e.invoiced,
            "hourly_rate_override": e.hourly_rate_override,
        }
        for e in entries
    ]
