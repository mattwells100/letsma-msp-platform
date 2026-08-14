"""
Server-rendered portal views (Jinja2 + Bootstrap) covering:
  - Internal technician dashboard (/dashboard)
  - Customer, ticket, billing, license, and endpoint list/detail pages
  - A simplified external customer-facing portal (/portal/{customer_id})

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


@router.get("/customers/{customer_id}")
def customer_detail_page(customer_id: str, request: Request, db: Session = Depends(get_db)):
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    tickets = db.query(models.Ticket).filter_by(customer_id=customer_id).order_by(models.Ticket.created_at.desc()).all()
    invoices = db.query(models.Invoice).filter_by(customer_id=customer_id).order_by(models.Invoice.created_at.desc()).all()
    endpoints = db.query(models.Endpoint).filter_by(customer_id=customer_id).all()
    license_summary = db.query(models.TenantLicenseSummary).filter_by(customer_id=customer_id).all()
    return templates.TemplateResponse("customer_detail.html", {
        "request": request, "customer": customer, "tickets": tickets, "invoices": invoices,
        "endpoints": endpoints, "license_summary": license_summary, "active_page": "customers",
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
    return templates.TemplateResponse("ticket_detail.html", {"request": request, "ticket": ticket, "active_page": "tickets"})


@router.get("/billing")
def billing_page(request: Request, db: Session = Depends(get_db)):
    invoices = db.query(models.Invoice).order_by(models.Invoice.created_at.desc()).all()
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    return templates.TemplateResponse("billing.html", {"request": request, "invoices": invoices, "customers": customers, "active_page": "billing"})


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
