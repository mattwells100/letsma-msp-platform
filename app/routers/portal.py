"""
Server-rendered portal views (Jinja2 + Bootstrap) covering:
  - Internal technician dashboard (/dashboard)
  - Customer, ticket, billing, license, and endpoint list/detail pages
  - A simplified external customer-facing portal (/portal/{customer_id})
  - Billing settings (customer billing config + license pricing)

This keeps the MVP dependency-light (no separate frontend build step).
For a production-grade UI, swap this for a React/Next.js SPA consuming the
same /api/* endpoints.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app import models

router = APIRouter(tags=["Portal"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/")
def root(request: Request, db: Session = Depends(get_db)):
    return dashboard(request, db)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    stats = {
        "customers": db.query(models.Customer).count(),
        "open_tickets": db.query(models.Ticket).filter(
            models.Ticket.status.in_(["New", "In Progress", "Waiting on Customer"])
        ).count(),
        "endpoints_online": db.query(models.Endpoint).filter_by(status="Online").count(),
        "endpoints_total": db.query(models.Endpoint).count(),
        "unpaid_invoices": db.query(models.Invoice).filter(
            models.Invoice.status.in_(["Draft", "Sent", "Overdue"])
        ).count(),
    }
    recent_tickets = db.query(models.Ticket).order_by(models.Ticket.created_at.desc()).limit(8).all()
    alerting_endpoints = db.query(models.Endpoint).filter(
        models.Endpoint.status.in_(["Warning", "Offline"])
    ).limit(8).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "stats": stats, "recent_tickets": recent_tickets,
        "alerting_endpoints": alerting_endpoints, "active_page": "dashboard",
    })


@router.get("/customers")
def customers_page(request: Request, db: Session = Depends(get_db)):
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    return templates.TemplateResponse("customers.html", {"request": request, "customers": customers, "active_page": "customers"})


def _contact_sort_key(contact):
    """
    Sorts contacts alphabetically by first name. Uses the dedicated
    first_name field when available (Graph-synced contacts), otherwise
    falls back to the first word of the 'name' field (manual contacts,
    which don't have first_name populated). Never returns None, so this
    is always safe to sort with (avoids a TypeError crash from comparing
    None to a string).
    """
    if contact.first_name:
        return contact.first_name.strip().lower()
    if contact.name:
        parts = contact.name.strip().split()
        return parts[0].lower() if parts else ""
    return ""


@router.get("/customers/{customer_id}")
def customer_detail_page(customer_id: str, request: Request, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    tickets = db.query(models.Ticket).filter_by(customer_id=customer_id).order_by(models.Ticket.created_at.desc()).all()
    invoices = db.query(models.Invoice).filter_by(customer_id=customer_id).order_by(models.Invoice.created_at.desc()).all()
    endpoints = db.query(models.Endpoint).filter_by(customer_id=customer_id).all()
    license_summary = db.query(models.TenantLicenseSummary).filter_by(customer_id=customer_id).all()
    sorted_contacts = sorted(customer.contacts, key=_contact_sort_key)
    return templates.TemplateResponse("customer_detail.html", {
        "request": request, "customer": customer, "tickets": tickets, "invoices": invoices,
        "endpoints": endpoints, "license_summary": license_summary, "sorted_contacts": sorted_contacts,
        "active_page": "customers",
    })


@router.get("/tickets")
def tickets_page(request: Request, db: Session = Depends(get_db)):
    tickets = db.query(models.Ticket).order_by(models.Ticket.created_at.desc()).all()
    return templates.TemplateResponse("tickets.html", {"request": request, "tickets": tickets, "active_page": "tickets"})


@router.get("/tickets/{ticket_id}")
def ticket_detail_page(ticket_id: str, request: Request, db: Session = Depends(get_db)):
    ticket = db.query(models.Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    time_entries = (
        db.query(models.TimeEntry)
        .filter_by(ticket_id=ticket_id)
        .order_by(models.TimeEntry.work_date.desc())
        .all()
    )
    return templates.TemplateResponse("ticket_detail.html", {
        "request": request, "ticket": ticket, "time_entries": time_entries, "active_page": "tickets",
    })


@router.get("/billing")
def billing_page(request: Request, db: Session = Depends(get_db)):
    invoices = db.query(models.Invoice).order_by(models.Invoice.created_at.desc()).all()
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    return templates.TemplateResponse("billing.html", {"request": request, "invoices": invoices, "customers": customers, "active_page": "billing"})


@router.get("/billing-settings")
def billing_settings_page(request: Request, db: Session = Depends(get_db)):
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    license_prices = db.query(models.LicensePrice).all()

    priced_skus = {p.sku_part_number for p in license_prices}
    assigned_skus = {
        row[0] for row in db.query(models.LicenseAssignment.sku_part_number).distinct().all()
    }
    known_skus = sorted(priced_skus | assigned_skus)

    return templates.TemplateResponse("billing_settings.html", {
        "request": request,
        "customers": customers,
        "license_prices": license_prices,
        "known_skus": known_skus,
        "active_page": "billing-settings",
    })


@router.get("/licenses")
def licenses_page(request: Request, db: Session = Depends(get_db)):
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    summary_rows = db.query(models.TenantLicenseSummary).all()
    totals = {}
    for row in summary_rows:
        totals.setdefault(row.friendly_name or row.sku_part_number, {"enabled": 0, "consumed": 0})
        totals[row.friendly_name or row.sku_part_number]["enabled"] += row.enabled_units
        totals[row.friendly_name or row.sku_part_number]["consumed"] += row.consumed_units
    return templates.TemplateResponse("licenses.html", {"request": request, "customers": customers, "totals": totals, "active_page": "licenses"})


@router.get("/endpoints")
def endpoints_page(request: Request, db: Session = Depends(get_db)):
    endpoints = db.query(models.Endpoint).all()
    return templates.TemplateResponse("endpoints.html", {"request": request, "endpoints": endpoints, "active_page": "endpoints"})


@router.get("/portal/{customer_id}")
def customer_portal(customer_id: str, request: Request, db: Session = Depends(get_db)):
    """Simplified external-facing self-service portal for a customer:
    view + raise tickets, view invoices. In production, gate this behind
    Entra External ID (CIAM) or a magic-link token instead of a raw path param."""
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    tickets = db.query(models.Ticket).filter_by(customer_id=customer_id).order_by(models.Ticket.created_at.desc()).all()
    invoices = db.query(models.Invoice).filter_by(customer_id=customer_id).order_by(models.Invoice.created_at.desc()).all()
    return templates.TemplateResponse("portal_customer.html", {
        "request": request, "customer": customer, "tickets": tickets, "invoices": invoices,
    })
