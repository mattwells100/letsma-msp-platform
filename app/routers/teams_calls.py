from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.teams_call_service import assign_call_interaction, sync_recent_calls

router = APIRouter(prefix="/api/calls", tags=["Teams Calls"])


class CallAssignmentRequest(BaseModel):
    customer_id: str
    contact_id: str | None = None


@router.post("/sync")
async def sync_teams_calls(hours: int = Query(default=24, ge=1, le=168), db: Session = Depends(get_db)):
    try:
        return await sync_recent_calls(db, since=datetime.utcnow() - timedelta(hours=hours))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Microsoft Graph Teams call sync failed: {exc}")


@router.post("/{call_id}/assign")
def assign_call(call_id: str, payload: CallAssignmentRequest, db: Session = Depends(get_db)):
    try:
        interaction = assign_call_interaction(db, call_id, payload.customer_id, payload.contact_id)
    except ValueError as exc:
        message = str(exc)
        if message == "Call interaction not found":
            raise HTTPException(404, message)
        raise HTTPException(400, message)
    return {
        "ok": True,
        "call_id": interaction.id,
        "customer_id": interaction.customer_id,
        "contact_id": interaction.contact_id,
    }