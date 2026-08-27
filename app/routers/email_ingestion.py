"""
app/routers/email_ingestion.py

Endpoints to manually trigger a helpdesk-mailbox poll, and to manage the
excluded-sender list and auto-reply rules.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.database import get_db
from app import models
from app.services import email_ingestion_service

router = APIRouter(prefix="/api/email-ingestion", tags=["Email-to-Ticket"])


@router.post("/poll")
async def poll_helpdesk_inbox(db: Session = Depends(get_db)):
    """Manually trigger a check of the helpdesk mailbox for new emails.
    This same function is also called automatically on a schedule - see
    app/scheduler.py."""
    try:
        result = await email_ingestion_service.poll_and_process_helpdesk_inbox(db)
    except Exception as e:
        raise HTTPException(502, f"Failed to poll helpdesk mailbox: {e}")
    return result


# ---------------------------------------------------------------------------
# Excluded senders
# ---------------------------------------------------------------------------
class ExcludedSenderCreate(BaseModel):
    pattern: str  # exact email, or "*@domain.com"
    reason: Optional[str] = None


@router.get("/excluded-senders")
def list_excluded_senders(db: Session = Depends(get_db)):
    rows = db.query(models.ExcludedEmailSender).order_by(models.ExcludedEmailSender.pattern).all()
    return [{"id": r.id, "pattern": r.pattern, "reason": r.reason} for r in rows]


@router.post("/excluded-senders")
def add_excluded_sender(payload: ExcludedSenderCreate, db: Session = Depends(get_db)):
    existing = db.query(models.ExcludedEmailSender).filter_by(pattern=payload.pattern.strip().lower()).first()
    if existing:
        raise HTTPException(400, "This pattern is already excluded")
    row = models.ExcludedEmailSender(pattern=payload.pattern.strip().lower(), reason=payload.reason)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "pattern": row.pattern, "reason": row.reason}


@router.delete("/excluded-senders/{sender_id}")
def remove_excluded_sender(sender_id: str, db: Session = Depends(get_db)):
    row = db.query(models.ExcludedEmailSender).get(sender_id)
    if not row:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Auto-reply rules
# ---------------------------------------------------------------------------
class AutoReplyRuleCreate(BaseModel):
    name: str
    trigger_keywords: str  # comma-separated phrases
    reply_subject: str
    reply_body: str
    active: bool = True


@router.get("/auto-reply-rules")
def list_auto_reply_rules(db: Session = Depends(get_db)):
    rows = db.query(models.AutoReplyRule).order_by(models.AutoReplyRule.name).all()
    return [
        {"id": r.id, "name": r.name, "trigger_keywords": r.trigger_keywords,
         "reply_subject": r.reply_subject, "reply_body": r.reply_body, "active": r.active}
        for r in rows
    ]


@router.post("/auto-reply-rules")
def add_auto_reply_rule(payload: AutoReplyRuleCreate, db: Session = Depends(get_db)):
    row = models.AutoReplyRule(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name}


@router.put("/auto-reply-rules/{rule_id}")
def update_auto_reply_rule(rule_id: str, payload: AutoReplyRuleCreate, db: Session = Depends(get_db)):
    row = db.query(models.AutoReplyRule).get(rule_id)
    if not row:
        raise HTTPException(404, "Not found")
    for k, v in payload.model_dump().items():
        setattr(row, k, v)
    db.commit()
    return {"ok": True}


@router.delete("/auto-reply-rules/{rule_id}")
def delete_auto_reply_rule(rule_id: str, db: Session = Depends(get_db)):
    row = db.query(models.AutoReplyRule).get(rule_id)
    if not row:
        raise HTTPException(404, "Not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
