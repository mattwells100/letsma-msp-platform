from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import xero_service

router = APIRouter(prefix="/auth/xero", tags=["Xero OAuth"])


@router.get("/login")
def xero_login():
    """Kick off the Xero consent flow - open this URL in a browser once to connect Letsma's Xero org."""
    return RedirectResponse(xero_service.get_authorization_url())


@router.get("/callback")
async def xero_callback(code: str, state: str = "", db: Session = Depends(get_db)):
    try:
        token = await xero_service.exchange_code_for_token(db, code)
    except Exception as e:
        raise HTTPException(400, f"Xero token exchange failed: {e}")
    return {
        "ok": True,
        "message": "Xero connected successfully. Invoices can now be pushed automatically.",
        "xero_tenant_id": token.tenant_id,
    }
