"""
app/main.py

Letsma MSP Platform - main application entrypoint.

Run locally with:
    uvicorn app.main:app --reload --port 8000

API docs are auto-generated at /docs (Swagger UI) and /redoc.
"""
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.database import Base, engine
from app.config import settings
from app.deps import require_login_json
from app.routers import customers, tickets, billing, licenses, endpoints
from app.routers import webhooks_whatsapp, webhooks_teams, auth_xero, portal
from app.routers import admin_migrate, contacts_sync
from app.routers import amazon, time_entries
from app.routers import billing_config
from app.routers import email_ingestion
from app.routers import purchases
from app.scheduler import start_scheduler
from app.routers import ai_assist
from app.routers import auth as auth_login
from app.routers import admin_technicians
from app.routers import purchasing_email_ingestion, purchasing_email_admin
from app.routers import recurring_billing

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="Unified MSP platform: customers, billing (Xero), Microsoft 365 "
                 "license management, helpdesk with WhatsApp/Teams/Email ticket "
                 "logging, endpoint monitoring, and recurring billing with a "
                 "general purchasing module and profitability reporting.",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Staff login session cookie (Microsoft Entra ID SSO - see
# app/routers/auth.py). Signed with the existing SECRET_KEY via
# itsdangerous (already a dependency, no new package added).
# https_only=True is safe since Azure App Service always serves HTTPS;
# max_age=28800 is an 8-hour working-day session.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    https_only=True,
    same_site="lax",
    max_age=28800,
)

# Staff login (Microsoft Entra ID SSO) - deliberately UNGATED, this is the
# one place that must stay reachable while logged out.
app.include_router(auth_login.router)

# JSON APIs - now require a logged-in staff session (401 JSON if not).
# Note: the scheduled background pollers (helpdesk/orders mailbox) call
# their service functions directly, NOT through these HTTP endpoints, so
# gating the /poll routes here does not affect the automatic 5-minute
# scheduled jobs - it only means triggering a poll manually via curl now
# requires a valid session cookie (log in via the browser first).
app.include_router(customers.router, dependencies=[Depends(require_login_json)])
app.include_router(tickets.router, dependencies=[Depends(require_login_json)])
app.include_router(billing.router, dependencies=[Depends(require_login_json)])
app.include_router(licenses.router, dependencies=[Depends(require_login_json)])
app.include_router(endpoints.router, dependencies=[Depends(require_login_json)])


# Contacts (Microsoft 365 sync) - session-gated.
# admin_migrate stays UNGATED by session - it already has its own
# X-Agent-Key header check (_check_admin_key) and is called via curl/
# script for one-off schema migrations; adding a session requirement on
# top would break that existing scripted workflow.
app.include_router(admin_migrate.router)
app.include_router(contacts_sync.router, dependencies=[Depends(require_login_json)])

# Staff management (add/deactivate technicians who are allowed to log in)
# - same X-Agent-Key pattern as admin_migrate, deliberately UNGATED by
# session for the same reason (must be usable to add the SECOND
# technician before they've ever logged in themselves).
app.include_router(admin_technicians.router)

# Amazon CSV import + general purchasing module + helpdesk labour time entries
app.include_router(amazon.router, dependencies=[Depends(require_login_json)])
app.include_router(purchases.router, dependencies=[Depends(require_login_json)])
app.include_router(time_entries.router, dependencies=[Depends(require_login_json)])

# Per-customer billing configuration + license pricing + profitability reporting
app.include_router(billing_config.router, dependencies=[Depends(require_login_json)])

# Email-to-ticket ingestion (helpdesk@letsma.co.uk) - session-gated (the
# excluded-senders/auto-reply-rules management is sensitive). The
# scheduled poll job is unaffected - see note above.
app.include_router(email_ingestion.router, dependencies=[Depends(require_login_json)])

# Integration webhooks / OAuth - UNGATED. These are called by external
# services (WhatsApp, Teams, Xero) that have no Letsma staff session and
# never will - they authenticate via their own webhook secrets/OAuth
# state instead.
app.include_router(webhooks_whatsapp.router)
app.include_router(webhooks_teams.router)
app.include_router(auth_xero.router)

# Server-rendered portal (dashboard + customer self-service). NOT gated
# here at the router level, since this router also contains the external
# customer-facing /portal/{customer_id} route, which must stay reachable
# without a Letsma staff login. Instead, each STAFF-facing page route
# inside app/routers/portal.py individually depends on
# require_login_page (added directly to those route functions) - see
# that file for details.
app.include_router(portal.router)

app.include_router(ai_assist.router, dependencies=[Depends(require_login_json)])
app.include_router(purchasing_email_ingestion.router, dependencies=[Depends(require_login_json)])
app.include_router(purchasing_email_admin.router)
app.include_router(recurring_billing.router)

@app.on_event("startup")
async def _on_startup():
    """Starts the background scheduler that polls the helpdesk mailbox
    every few minutes. Safe to call even if email-to-ticket hasn't been
    configured yet - the scheduled job checks for credentials and skips
    silently if they're not set."""
    start_scheduler()


@app.get("/healthz", tags=["System"])
def health_check():
    db_backend = "unknown"
    if settings.DATABASE_URL.startswith("postgresql"):
        db_backend = "postgresql"
    elif settings.DATABASE_URL.startswith("sqlite"):
        db_backend = "sqlite"
    agent_key_preview = settings.AGENT_API_KEY[:6] if settings.AGENT_API_KEY else "EMPTY"
    agent_key_length = len(settings.AGENT_API_KEY) if settings.AGENT_API_KEY else 0
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "database_backend": db_backend,
        "agent_key_preview": agent_key_preview,
        "agent_key_length": agent_key_length,
    }
