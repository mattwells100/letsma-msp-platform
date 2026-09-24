from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.teams_call_service import sync_recent_calls

router = APIRouter(prefix="/api/calls", tags=["Teams Calls"])


@router.post("/sync")
async def sync_teams_calls(db: Session = Depends(get_db)):
    try:
        return await sync_recent_calls(db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"Microsoft Graph Teams call sync failed: {exc}")