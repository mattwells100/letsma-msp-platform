from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.services import teams_service, whatsapp_service
from app.services.ticket_numbering import next_ticket_number

router = APIRouter(prefix="/api/tickets", tags=["Helpdesk"])

# SLA targets (hours) by priority - used to auto-compute sla_due_at
SLA_HOURS = {"Critical": 2, "High": 4, "Normal": 8, "Low": 24}


@router.get("/", response_model=List[schemas.TicketOut])
def list_tickets(status: Optional[str] = None, customer_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.Ticket)
    if status:
        q = q.filter(models.Ticket.status == status)
    if customer_id:
        q = q.filter(models.Ticket.customer_id == customer_id)
    return q.order_by(models.Ticket.created_at.desc()).all()


@router.post("/", response_model=schemas.TicketOut)
def create_ticket(payload: schemas.TicketCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(payload.customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")

    data = payload.model_dump()
    priority = data.get("priority") or "Normal"

    ticket = models.Ticket(
        ticket_number=next_ticket_number(db),
        customer_id=data["customer_id"],
        contact_id=data.get("contact_id"),
        subject=data["subject"],
        description=data.get("description"),
        priority=priority,
        source=data.get("source") or "Portal",
        external_ref=data.get("external_ref"),
        sla_due_at=datetime.utcnow() + timedelta(hours=SLA_HOURS.get(priority, 8)),
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    # Fire-and-forget Teams notification (does nothing if webhook not configured)
    background_tasks.add_task(_notify_teams_new_ticket, ticket.id)
    return ticket


async def _notify_teams_new_ticket(ticket_id: str):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        ticket = db.query(models.Ticket).get(ticket_id)
        if ticket:
            await teams_service.notify_new_ticket(ticket, ticket.customer)
    finally:
        db.close()


@router.get("/{ticket_id}", response_model=schemas.TicketOut)
def get_ticket(ticket_id: str, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.patch("/{ticket_id}", response_model=schemas.TicketOut)
def update_ticket(ticket_id: str, payload: schemas.TicketUpdate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    updates = payload.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(ticket, k, v)

    if updates.get("status") in ("Resolved", "Closed"):
        ticket.resolved_at = datetime.utcnow()

    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ticket)

    if "status" in updates:
        background_tasks.add_task(
            _notify_whatsapp_status, ticket.id,
            f"Update on ticket #{ticket.ticket_number} ({ticket.subject}): status is now '{updates['status']}'."
        )
    return ticket


async def _notify_whatsapp_status(ticket_id: str, message: str):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        ticket = db.query(models.Ticket).get(ticket_id)
        if ticket:
            try:
                await whatsapp_service.notify_ticket_update(db, ticket, message)
            except Exception:
                pass  # WhatsApp not configured / customer has no number - safe to ignore in MVP
    finally:
        db.close()


@router.post("/{ticket_id}/comments")
def add_comment(ticket_id: str, payload: schemas.TicketCommentCreate, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    comment = models.TicketComment(ticket_id=ticket_id, **payload.model_dump())
    db.add(comment)
    ticket.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(comment)
    return {"id": comment.id, "created_at": comment.created_at}
