"""
app/routers/auth.py

Staff login via Microsoft Entra ID SSO (Authorization Code flow). Letsma
staff sign in with their existing @letsma.co.uk Microsoft 365 account -
no separate platform password to manage.

Flow:
  1. GET /auth/login   - shows a simple "Sign in with Microsoft" page (or
                          could redirect immediately - kept as a landing
                          page so a stale bookmark to a protected page
                          doesn't bounce straight into a confusing
                          Microsoft redirect with no context).
  2. GET /auth/start    - generates a CSRF state value, stores it in the
                          session, redirects to Microsoft's login page.
  3. GET /auth/callback - Microsoft redirects back here with a one-time
                          code. Exchanges it for the signed-in user's
                          identity claims, verifies the tenant matches
                          Letsma's own tenant (defense in depth on top of
                          the single-tenant app registration), then looks
                          up a matching Technician row:
                            - Found + active: log them in.
                            - Found + inactive: access denied.
                            - Not found, but the Technician table is
                              completely empty: bootstrap this person as
                              the first Admin (solves the chicken-and-egg
                              problem of needing an existing technician
                              to add the first technician).
                            - Not found, table non-empty: access denied -
                              an existing admin must add them first via
                              POST /api/admin/technicians (see
                              app/routers/admin_technicians.py).
  4. GET /auth/logout   - clears the local session only (does NOT log the
                          user out of Microsoft 365 / other Microsoft
                          sites - a deliberate choice to avoid surprising
                          side effects on unrelated Microsoft sessions).

This router is NEVER gated behind require_login_page/require_login_json
(that would create an unbreakable redirect loop) - it's the one place in
the app that must always stay reachable while logged out.
"""
import secrets

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.config import settings
from app import models
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["Auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login")
def login_page(request: Request):
    """Simple standalone landing page with a 'Sign in with Microsoft'
    button - does NOT extend base.html (which assumes a logged-in staff
    member and always renders the full sidebar nav)."""
    return templates.TemplateResponse("login.html", {"request": request})


@router.get("/start")
def start_login(request: Request):
    if not settings.AUTH_TENANT_ID or not settings.AUTH_CLIENT_ID or not settings.AUTH_CLIENT_SECRET:
        raise HTTPException(
            500,
            "Staff login is not configured yet. Set AUTH_TENANT_ID, AUTH_CLIENT_ID, "
            "and AUTH_CLIENT_SECRET in Key Vault, then restart the app.",
        )
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(auth_service.get_auth_url(state))


@router.get("/callback")
def auth_callback(request: Request, code: str = None, state: str = None, error: str = None, error_description: str = None):
    if error:
        return templates.TemplateResponse("access_denied.html", {
            "request": request,
            "reason": f"Microsoft sign-in was cancelled or failed: {error_description or error}",
        }, status_code=400)

    expected_state = request.session.pop("oauth_state", None)
    if not state or not expected_state or state != expected_state:
        return templates.TemplateResponse("access_denied.html", {
            "request": request,
            "reason": "Login session expired or is invalid - please try signing in again.",
        }, status_code=400)

    if not code:
        return templates.TemplateResponse("access_denied.html", {
            "request": request, "reason": "No authorization code received from Microsoft.",
        }, status_code=400)

    result = auth_service.acquire_token_by_auth_code(code)
    if "error" in result:
        return templates.TemplateResponse("access_denied.html", {
            "request": request,
            "reason": f"Sign-in failed: {result.get('error_description', result.get('error'))}",
        }, status_code=400)

    claims = result.get("id_token_claims", {})
    tenant_id = claims.get("tid")
    if tenant_id != settings.AUTH_TENANT_ID:
        return templates.TemplateResponse("access_denied.html", {
            "request": request,
            "reason": "This Microsoft account does not belong to Letsma's organization.",
        }, status_code=403)

    email = (claims.get("preferred_username") or claims.get("email") or "").strip().lower()
    name = claims.get("name") or email
    object_id = claims.get("oid")

    if not email:
        return templates.TemplateResponse("access_denied.html", {
            "request": request, "reason": "Microsoft did not return an email address for this account.",
        }, status_code=400)

    db: Session = SessionLocal()
    try:
        technician = db.query(models.Technician).filter(models.Technician.email.ilike(email)).first()

        if not technician:
            total_technicians = db.query(models.Technician).count()
            if total_technicians == 0:
                # Bootstrap: first-ever login becomes the first Admin.
                # Solves the chicken-and-egg problem of needing an
                # existing technician to be able to add technicians.
                technician = models.Technician(
                    name=name, email=email, password_hash=None,
                    role="Admin", entra_object_id=object_id, active=True,
                )
                db.add(technician)
                db.commit()
                db.refresh(technician)
            else:
                return templates.TemplateResponse("access_denied.html", {
                    "request": request,
                    "reason": f"{name} ({email}) is not registered as a technician on this platform. "
                              f"Ask an existing administrator to add you first.",
                }, status_code=403)
        elif not technician.active:
            return templates.TemplateResponse("access_denied.html", {
                "request": request,
                "reason": f"Your technician account ({email}) has been deactivated. Contact your administrator.",
            }, status_code=403)
        else:
            # Keep entra_object_id / name in sync on every login, in case
            # this is the first login since the column was added, or the
            # display name changed in Entra.
            technician.entra_object_id = object_id
            if name:
                technician.name = name
            db.commit()

        request.session["user"] = {
            "technician_id": technician.id,
            "name": technician.name,
            "email": technician.email,
            "role": technician.role,
        }
    finally:
        db.close()

    return RedirectResponse("/dashboard", status_code=303)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/login", status_code=303)


@router.get("/me")
def whoami(request: Request):
    """Returns the current session's user info, or null if not logged in.
    Handy for quickly verifying login worked (curl/browser)."""
    return {"user": request.session.get("user")}
