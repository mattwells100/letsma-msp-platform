"""
app/routers/admin_technicians.py

Minimal management of the Technician allowlist that gates Entra SSO login
(see app/routers/auth.py) - only pre-registered, active technicians can
sign in. Uses the same X-Agent-Key admin auth pattern as admin_migrate.py
(deliberately NOT session-login-gated, so it stays usable via curl/script
even before anyone has logged in - e.g. to add the second technician
before they've ever signed in themselves).
"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app import models

router = APIRouter(prefix="/api/admin/technicians", tags=["Admin"])


def _check_agent_key(x_agent_key: str = Header(None)):
    import os
    expected = os.environ.get("AGENT_API_KEY")
    if not expected or x_agent_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Agent-Key")


class TechnicianCreate(BaseModel):
    name: str
    email: str
    role: str = "Technician"  # "Technician" | "Manager" | "Admin"


@router.get("/", response_model=None)
def list_technicians(db: Session = Depends(get_db), _=Depends(_check_agent_key)):
    rows = db.query(models.Technician).order_by(models.Technician.name).all()
    return [
        {"id": t.id, "name": t.name, "email": t.email, "role": t.role, "active": t.active}
        for t in rows
    ]


@router.post("/")
def add_technician(payload: TechnicianCreate, db: Session = Depends(get_db), _=Depends(_check_agent_key)):
    """
    Pre-registers a staff member so they can sign in via Microsoft SSO.
    No password is set - they authenticate entirely via Entra ID; this
    just controls WHO is allowed to log in and what role they get.
    """
    email = payload.email.strip().lower()
    existing = db.query(models.Technician).filter(models.Technician.email.ilike(email)).first()
    if existing:
        raise HTTPException(400, f"A technician with email '{email}' already exists (id={existing.id})")

    technician = models.Technician(
        name=payload.name, email=email, password_hash=None,
        role=payload.role, active=True,
    )
    db.add(technician)
    db.commit()
    db.refresh(technician)
    return {"id": technician.id, "name": technician.name, "email": technician.email, "role": technician.role}


@router.patch("/{technician_id}/deactivate")
def deactivate_technician(technician_id: str, db: Session = Depends(get_db), _=Depends(_check_agent_key)):
    """Revokes login access without deleting the row (preserves any
    historical references, e.g. Ticket.assigned_to)."""
    technician = db.query(models.Technician).get(technician_id)
    if not technician:
        raise HTTPException(404, "Technician not found")
    technician.active = False
    db.commit()
    return {"ok": True, "id": technician.id, "active": technician.active}


@router.patch("/{technician_id}/reactivate")
def reactivate_technician(technician_id: str, db: Session = Depends(get_db), _=Depends(_check_agent_key)):
    technician = db.query(models.Technician).get(technician_id)
    if not technician:
        raise HTTPException(404, "Technician not found")
    technician.active = True
    db.commit()
    return {"ok": True, "id": technician.id, "active": technician.active}
