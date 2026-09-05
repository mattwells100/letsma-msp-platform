from app.models import LicenseAssignment
"""
Server-rendered portal views (Jinja2 + Bootstrap) covering:
  - Internal technician dashboard (/dashboard)
  - Customer, ticket, billing, license, and endpoint list/detail pages
  - A simplified external customer-facing portal (/portal/{customer_id})
  - Billing settings (customer billing config + license pricing)
  - Email settings (excluded senders for helpdesk email-to-ticket)

This keeps the MVP dependency-light (no separate frontend build step).
For a production-grade UI, swap this for a React/Next.js SPA consuming the
same /api/* endpoints.

STAFF LOGIN (Microsoft Entra ID SSO - see app/routers/auth.py): every
STAFF-facing page route below individually depends on require_login_page,
which redirects to /auth/login if no one is signed in. This is applied
per-route rather than once for the whole router, because this file ALSO
contains customer_portal() (the external customer-facing
/portal/{customer_id} route), which must stay reachable WITHOUT a Letsma
staff login - customers don't have Letsma Azure accounts. Do not add
require_login_page to customer_portal().
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app import models
from app.deps import require_login_page

router = APIRouter(tags=["Portal"])
templates = Jinja2Templates(directory="app/templates")

from app.models import RecurringBillingItem


@router.get("/")
def root(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    return dashboard(request, db)


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    stats = {
        "customers": db.query(models.Customer).count(),
        "open_tickets": db.query(models.Ticket).filter(
            models.Ticket.status.in_(["New", "In Progress", "Waiting on Customer"])
        ).filter(models.Ticket.deleted_at.is_(None)).count(),
        "endpoints_online": db.query(models.Endpoint).filter_by(status="Online").count(),
        "endpoints_total": db.query(models.Endpoint).count(),
        "unpaid_invoices": db.query(models.Invoice).filter(
            models.Invoice.status.in_(["Draft", "Sent", "Overdue"])
        ).count(),
    }
    recent_tickets = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None)).order_by(models.Ticket.created_at.desc()).limit(8).all()
    alerting_endpoints = db.query(models.Endpoint).filter(
        models.Endpoint.status.in_(["Warning", "Offline"])
    ).limit(8).all()
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "stats": stats, "recent_tickets": recent_tickets,
        "alerting_endpoints": alerting_endpoints, "active_page": "dashboard",
    })


@router.get("/customers")
def customers_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
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
def customer_detail_page(customer_id: str, request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
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


@router.get("/purchases")
def purchases_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    customers = db.query(models.Customer).order_by(models.Customer.name).all()

    needs_review_orders = (
        db.query(models.AmazonOrder)
        .filter(models.AmazonOrder.extraction_status.in_(["needs_review", "failed"]))
        .order_by(models.AmazonOrder.ingested_at.asc())
        .all()
    )

    all_orders = db.query(models.AmazonOrder).order_by(models.AmazonOrder.order_date.desc()).all()

    return templates.TemplateResponse("purchases.html", {
        "request": request,
        "customers": customers,
        "needs_review_orders": needs_review_orders,
        "all_orders": all_orders,
        "active_page": "purchases",
    })


@router.get("/tickets")
def tickets_page(request: Request, unassigned_only: bool = False, db: Session = Depends(get_db), _=Depends(require_login_page)):
    """
    unassigned_only=true filters the list down to tickets with no
    customer match - e.g. emails auto-ingested from the helpdesk mailbox
    where the sender's address couldn't be matched to any known
    customer/contact. Lets a technician quickly triage these for manual
    customer assignment. The count is always computed (regardless of the
    current filter) so the toggle link can show how many are waiting.
    """
    query = db.query(models.Ticket).filter(models.Ticket.deleted_at.is_(None))
    if unassigned_only:
        query = query.filter(models.Ticket.customer_id.is_(None))
    tickets = query.order_by(models.Ticket.created_at.desc()).all()
    unassigned_count = db.query(models.Ticket).filter(models.Ticket.customer_id.is_(None)).filter(models.Ticket.deleted_at.is_(None)).count()
    return templates.TemplateResponse("tickets.html", {
        "request": request, "tickets": tickets, "active_page": "tickets",
        "unassigned_only": unassigned_only, "unassigned_count": unassigned_count,
    })


@router.get("/tickets/{ticket_id}")
def ticket_detail_page(ticket_id: str, request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    ticket = db.query(models.Ticket).get(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    time_entries = (
        db.query(models.TimeEntry)
        .filter_by(ticket_id=ticket_id)
        .order_by(models.TimeEntry.work_date.desc())
        .all()
    )
    # Needed for the Customer assignment dropdown on the ticket detail
    # page (lets a technician assign/reassign the customer, e.g. for a
    # ticket auto-created from an unmatched helpdesk email).
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    return templates.TemplateResponse("ticket_detail.html", {
        "request": request, "ticket": ticket, "time_entries": time_entries, "active_page": "tickets",
        "customers": customers,
    })


@router.get("/billing")
def billing_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    invoices = db.query(models.Invoice).order_by(models.Invoice.created_at.desc()).all()
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    return templates.TemplateResponse("billing.html", {"request": request, "invoices": invoices, "customers": customers, "active_page": "billing"})

@router.get("/customers/{customer_id}/recurring-billing")
def customer_recurring_billing(
    request: Request,
    customer_id: str,
    db: Session = Depends(get_db),
):
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id)
        .first()
    )

    items = (
        db.query(RecurringBillingItem)
        .filter(
            RecurringBillingItem.customer_id == customer_id
        )
        .all()
    )

    return templates.TemplateResponse(
        "customer_recurring_billing.html",
        {
            "request": request,
            "customer": customer,
            "items": items,
            "active_page": "customers",
        },
    )

@router.get("/billing-settings")
def billing_settings_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    license_prices = db.query(models.LicensePrice).all()

    priced_skus = {p.sku_part_number for p in license_prices}
    assigned_skus = {
        row[0] for row in db.query(models.LicenseAssignment.sku_part_number).distinct().all()
    }
    
    all_assignments = db.query(LicenseAssignment).all()

    sku_lookup = {}

    for a in all_assignments:
        sku_lookup[a.sku_part_number] = (
            a.friendly_name or a.sku_part_number
        )

    known_skus = sorted(
        sku_lookup.items(),
        key=lambda x: x[1]
    )


    return templates.TemplateResponse("billing_settings.html", {
        "request": request,
        "customers": customers,
        "license_prices": license_prices,
        "known_skus": known_skus,
        "active_page": "billing-settings",
    })


@router.get("/email-settings")
def email_settings_page(request: Request, _=Depends(require_login_page)):
    """Manage the helpdesk email-to-ticket excluded-senders list (see
    app/services/email_ingestion_service.py / app/routers/email_ingestion.py
    for the underlying logic and API)."""
    return templates.TemplateResponse("email_settings.html", {
        "request": request, "active_page": "email-settings",
    })


@router.get("/licenses")
def licenses_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    customers = db.query(models.Customer).order_by(models.Customer.name).all()
    summary_rows = db.query(models.TenantLicenseSummary).all()
    totals = {}
    for row in summary_rows:
        totals.setdefault(row.friendly_name or row.sku_part_number, {"enabled": 0, "consumed": 0})
        totals[row.friendly_name or row.sku_part_number]["enabled"] += row.enabled_units
        totals[row.friendly_name or row.sku_part_number]["consumed"] += row.consumed_units
    return templates.TemplateResponse("licenses.html", {"request": request, "customers": customers, "totals": totals, "active_page": "licenses"})


@router.get("/endpoints")
def endpoints_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    endpoints = db.query(models.Endpoint).all()
    return templates.TemplateResponse("endpoints.html", {"request": request, "endpoints": endpoints, "active_page": "endpoints"})


@router.get("/portal/{customer_id}")
def customer_portal(customer_id: str, request: Request, db: Session = Depends(get_db)):
    """Simplified external-facing self-service portal for a customer:
    view + raise tickets, view invoices. In production, gate this behind
    Entra External ID (CIAM) or a magic-link token instead of a raw path param.

    DELIBERATELY NOT gated by require_login_page - customers don't have
    Letsma Azure accounts, so this must stay reachable without a staff
    login. Do not add _=Depends(require_login_page) here."""
    customer = db.query(models.Customer).get(customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    tickets = db.query(models.Ticket).filter_by(customer_id=customer_id).order_by(models.Ticket.created_at.desc()).all()
    invoices = db.query(models.Invoice).filter_by(customer_id=customer_id).order_by(models.Invoice.created_at.desc()).all()
    return templates.TemplateResponse("portal_customer.html", {
        "request": request, "customer": customer, "tickets": tickets, "invoices": invoices,
    })


@router.get("/recurring-catalog")
def recurring_catalog_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    items = (
        db.query(models.RecurringBillingCatalogItem)
        .order_by(models.RecurringBillingCatalogItem.name)
        .all()
    )
    return templates.TemplateResponse("recurring_catalog.html", {
        "request": request, "items": items, "active_page": "recurring-catalog",
    })


@router.get("/billing-preview")
def billing_preview_page(request: Request, db: Session = Depends(get_db), _=Depends(require_login_page)):
    # Only DRAFT invoices that have NOT been pushed to Xero are shown for
    # review/approval - anything already synced is out of scope here.
    drafts = (
        db.query(models.Invoice)
        .filter(models.Invoice.xero_invoice_id.is_(None))
        .filter(models.Invoice.status == models.InvoiceStatus.DRAFT)
        .order_by(models.Invoice.created_at.desc())
        .all()
    )
    grand_subtotal = sum((inv.subtotal or 0) for inv in drafts)
    grand_tax = sum((inv.tax_total or 0) for inv in drafts)
    grand_total = sum((inv.total or 0) for inv in drafts)
    return templates.TemplateResponse("billing_preview.html", {
        "request": request, "drafts": drafts,
        "grand_subtotal": grand_subtotal, "grand_tax": grand_tax, "grand_total": grand_total,
        "active_page": "billing",
    })
