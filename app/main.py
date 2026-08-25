"""
Letsma MSP Platform - main application entrypoint.

Run locally with:
    uvicorn app.main:app --reload --port 8000

API docs are auto-generated at /docs (Swagger UI) and /redoc.
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app.config import settings
from app.routers import customers, tickets, billing, licenses, endpoints
from app.routers import webhooks_whatsapp, webhooks_teams, auth_xero, portal
from app.routers import admin_migrate, contacts_sync

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.APP_NAME,
    description="Unified MSP platform: customers, billing (Xero), Microsoft 365 "
                 "license management, helpdesk with WhatsApp/Teams ticket logging, "
                 "and endpoint monitoring.",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

# JSON APIs
app.include_router(customers.router)
app.include_router(tickets.router)
app.include_router(billing.router)
app.include_router(licenses.router)
app.include_router(endpoints.router)

# Integration webhooks / OAuth
app.include_router(webhooks_whatsapp.router)
app.include_router(webhooks_teams.router)
app.include_router(auth_xero.router)

# Server-rendered portal (dashboard + customer self-service)
app.include_router(portal.router)
app.include_router(admin_migrate.router)
app.include_router(contacts_sync.router)


@app.get("/healthz", tags=["System"])
def health_check():
    db_backend = "unknown"
    if settings.DATABASE_URL.startswith("postgresql"):
        db_backend = "postgresql"
    elif settings.DATABASE_URL.startswith("sqlite"):
        db_backend = "sqlite"
    return {"status": "ok", "app": settings.APP_NAME, "database_backend": db_backend}
