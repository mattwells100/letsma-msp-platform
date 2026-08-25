"""
A small, protected, idempotent migration endpoint that adds the new Contact
columns to the live Postgres database.
"""
from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api/admin", tags=["Admin - Schema Migration"])


def _check_admin_key(x_agent_key: str = Header(default="")):
    if x_agent_key != settings.AGENT_API_KEY:
        raise HTTPException(401, "Invalid admin key")


@router.post("/migrate-contacts-schema")
def migrate_contacts_schema(db: Session = Depends(get_db), _=Depends(_check_admin_key)):
    statements = [
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS first_name VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_name VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS business_phone VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS mobile_phone VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS graph_user_id VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'manual'",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_synced_from_graph TIMESTAMP",
    ]
    applied = []
    for stmt in statements:
        db.execute(text(stmt))
        applied.append(stmt)
    db.commit()
    return {"ok": True, "statements_applied": applied}