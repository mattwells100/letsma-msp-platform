"""
SQLAlchemy ORM models for the Letsma MSP Platform.

Modules covered:
  - Customers & Contacts (incl. Microsoft 365 contact sync fields)
  - Helpdesk (Tickets, Comments, multi-channel Sources incl. WhatsApp/Teams/Portal/Email)
  - Billing (Invoices, Line items, Xero sync state, recurring-billing engine)
  - Microsoft 365 License management (incl. sell price + cost price for profitability)
  - Endpoint monitoring (agents, heartbeats, alerts)
  - Staff/Technician users
  - Integration credential/token storage (OAuth tokens for Xero, Graph)
  - Helpdesk labour time tracking + general purchasing (any supplier) + licence pricing
  - Email-to-ticket ingestion (excluded senders, auto-reply rules, processed emails)
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, Enum
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class TicketStatus(str, enum.Enum):
    NEW = "New"
    IN_PROGRESS = "In Progress"
    WAITING_ON_CUSTOMER = "Waiting on Customer"
    RESOLVED = "Resolved"
    CLOSED = "Closed"


class TicketPriority(str, enum.Enum):
    LOW = "Low"
    NORMAL = "Normal"
    HIGH = "High"
    CRITICAL = "Critical"


class TicketSource(str, enum.Enum):
    PORTAL = "Portal"
    EMAIL = "Email"
    WHATSAPP = "WhatsApp"
    TEAMS = "Teams"
    PHONE = "Phone"
    AGENT_ALERT = "Endpoint Alert"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "Draft"
    SENT = "Sent"
    PAID = "Paid"
    OVERDUE = "Overdue"
    VOID = "Void"


class EndpointStatus(str, enum.Enum):
    ONLINE = "Online"
    OFFLINE = "Offline"
    WARNING = "Warning"
    UNKNOWN = "Unknown"


# ---------------------------------------------------------------------------
# Core entities
# ---------------------------------------------------------------------------
class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    trading_name = Column(String, nullable=True)
    address = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    account_manager = Column(String, nullable=True)
    status = Column(String, default="Active")  # Active, Onboarding, Offboarded
    xero_contact_id = Column(String, nullable=True)   # link to Xero Contact
    m365_tenant_id = Column(String, nullable=True)     # customer's Entra tenant (for Graph/GDAP)
    whatsapp_number = Column(String, nullable=True)    # primary WhatsApp contact number
    created_at = Column(DateTime, default=datetime.utcnow)

    # --- Billing engine configuration ---
    billing_type = Column(String, default="payg")            # "payg" or "contract"
    monthly_support_fee = Column(Float, default=0.0)          # used when billing_type == "contract"
    payg_hourly_rate = Column(Float, default=0.0)             # used when billing_type == "payg"
    amazon_markup_percent = Column(Float, default=0.0)        # markup %, applied to ALL purchases (any supplier), not just Amazon
    license_billing_mode = Column(String, default="none")     # "none" | "all" | "selected"
    licensed_skus_billed = Column(String, nullable=True)      # comma-separated sku_part_number list, only used when mode == "selected"

    contacts = relationship("Contact", back_populates="customer", cascade="all, delete-orphan")
    tickets = relationship("Ticket", back_populates="customer", cascade="all, delete-orphan")
    invoices = relationship("Invoice", back_populates="customer", cascade="all, delete-orphan")
    licenses = relationship("LicenseAssignment", back_populates="customer", cascade="all, delete-orphan")
    endpoints = relationship("Endpoint", back_populates="customer", cascade="all, delete-orphan")
    time_entries = relationship("TimeEntry", back_populates="customer", cascade="all, delete-orphan")
    amazon_orders = relationship("AmazonOrder", back_populates="customer")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=gen_id)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    name = Column(String, nullable=False)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    business_phone = Column(String, nullable=True)
    mobile_phone = Column(String, nullable=True)
    whatsapp_number = Column(String, nullable=True)
    role = Column(String, nullable=True)
    is_primary = Column(Boolean, default=False)
    graph_user_id = Column(String, nullable=True)     # Entra ID object ID, used to safely re-sync without duplicating
    source = Column(String, default="manual")          # "manual" or "graph_sync"
    last_synced_from_graph = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="contacts")


class Technician(Base):
    __tablename__ = "technicians"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="Technician")  # Technician, Manager, Admin
    teams_upn = Column(String, nullable=True)
    active = Column(Boolean, default=True)


# ---------------------------------------------------------------------------
# Helpdesk
# ---------------------------------------------------------------------------
class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(String, primary_key=True, default=gen_id)
    ticket_number = Column(Integer, unique=True, autoincrement=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=True)
    subject = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(Enum(TicketStatus), default=TicketStatus.NEW)
    priority = Column(Enum(TicketPriority), default=TicketPriority.NORMAL)
    source = Column(Enum(TicketSource), default=TicketSource.PORTAL)
    assigned_to = Column(String, ForeignKey("technicians.id"), nullable=True)
    external_ref = Column(String, nullable=True)  # e.g. WhatsApp message id, Teams message id, email message id
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    sla_due_at = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="tickets")
    contact = relationship("Contact")
    technician = relationship("Technician")
    comments = relationship("TicketComment", back_populates="ticket", cascade="all, delete-orphan")


class TicketComment(Base):
    __tablename__ = "ticket_comments"

    id = Column(String, primary_key=True, default=gen_id)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False)
    author = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    is_internal_note = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("Ticket", back_populates="comments")


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String, primary_key=True, default=gen_id)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    xero_invoice_id = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True)
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT)
    currency = Column(String, default="GBP")
    subtotal = Column(Float, default=0.0)
    tax_total = Column(Float, default=0.0)
    total = Column(Float, default=0.0)
    issue_date = Column(DateTime, default=datetime.utcnow)
    due_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Identifies the recurring period this invoice covers, so the monthly
    # generator can detect "already billed this period" and refuse to
    # create a duplicate.
    billing_period_start = Column(DateTime, nullable=True)
    billing_period_end = Column(DateTime, nullable=True)

    customer = relationship("Customer", back_populates="invoices")
    line_items = relationship("InvoiceLineItem", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"

    id = Column(String, primary_key=True, default=gen_id)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=False)
    description = Column(String, nullable=False)
    quantity = Column(Float, default=1.0)
    unit_price = Column(Float, default=0.0)
    account_code = Column(String, default="200")  # Xero chart-of-accounts code
    tax_type = Column(String, default="OUTPUT2")  # Xero UK 20% VAT on sales

    invoice = relationship("Invoice", back_populates="line_items")


class TimeEntry(Base):
    """A unit of billable (or non-billable) helpdesk labour, logged against
    a ticket. PAYG customers are invoiced based on the sum of unbilled
    billable hours each month; contract customers can still log time for
    reporting/visibility even though it doesn't directly drive their
    invoice total."""
    __tablename__ = "time_entries"

    id = Column(String, primary_key=True, default=gen_id)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    technician_name = Column(String, nullable=True)
    work_date = Column(DateTime, default=datetime.utcnow)
    hours = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    billable = Column(Boolean, default=True)
    hourly_rate_override = Column(Float, nullable=True)  # overrides customer.payg_hourly_rate for this entry, if set
    invoiced = Column(Boolean, default=False)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="time_entries")
    ticket = relationship("Ticket")


class AmazonOrder(Base):
    """
    A purchase order from ANY supplier, tracked for customer billing.

    Originally built for Amazon Business CSV imports (hence the class
    name, kept as-is to avoid an invasive table rename), this now
    doubles as a general PURCHASING module: orders can also be entered
    manually for any supplier (CDW, Ingram Micro, a local shop, etc.) via
    the /api/purchases/ endpoints. `supplier` distinguishes where an
    order came from; `source` distinguishes HOW it was captured
    ("csv_import" vs "manual").

    Starts unassigned; a technician assigns it to the customer it was
    purchased for. Once included on a generated invoice, `invoiced` is
    set so it's never billed twice. The markup applied at billing time
    comes from Customer.amazon_markup_percent, applied uniformly
    regardless of supplier.
    """
    __tablename__ = "amazon_orders"

    id = Column(String, primary_key=True, default=gen_id)
    amazon_order_id = Column(String, nullable=False, unique=True)  # the order's own reference number - prevents duplicate imports
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)  # null until assigned
    supplier = Column(String, nullable=True, default="Amazon")  # e.g. "Amazon", "CDW", "Ingram Micro"
    order_date = Column(DateTime, nullable=True)
    total = Column(Float, default=0.0)  # cost price, as paid to the supplier
    currency = Column(String, default="GBP")
    description = Column(Text, nullable=True)
    source = Column(String, default="csv_import")  # "csv_import" | "manual"
    invoiced = Column(Boolean, default=False)
    invoice_id = Column(String, ForeignKey("invoices.id"), nullable=True)
    imported_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="amazon_orders")
    line_items = relationship("AmazonOrderLineItem", back_populates="order", cascade="all, delete-orphan")


class AmazonOrderLineItem(Base):
    __tablename__ = "amazon_order_line_items"

    id = Column(String, primary_key=True, default=gen_id)
    order_id = Column(String, ForeignKey("amazon_orders.id"), nullable=False)
    description = Column(String, nullable=False)
    quantity = Column(Float, default=1.0)
    unit_price = Column(Float, default=0.0)

    order = relationship("AmazonOrder", back_populates="line_items")


class LicensePrice(Base):
    """
    Pricing for a given Microsoft 365 SKU:
      - monthly_unit_price: what you CHARGE the customer, per seat/month.
      - cost_price: what LETSMA PAYS (e.g. your CSP cost), per seat/month -
        used purely for profitability reporting, never billed to customers.

    One global default row per SKU (customer_id = null) is used unless a
    customer-specific override row exists for that same SKU.
    """
    __tablename__ = "license_prices"

    id = Column(String, primary_key=True, default=gen_id)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)  # null = global default price
    sku_part_number = Column(String, nullable=False)
    monthly_unit_price = Column(Float, default=0.0)  # sell price to the customer
    cost_price = Column(Float, nullable=True, default=0.0)  # Letsma's cost - for profitability reporting only


# ---------------------------------------------------------------------------
# Microsoft 365 Licensing
# ---------------------------------------------------------------------------
class LicenseAssignment(Base):
    """Represents one SKU assigned to one user within a customer's M365 tenant."""
    __tablename__ = "license_assignments"

    id = Column(String, primary_key=True, default=gen_id)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    user_upn = Column(String, nullable=False)
    display_name = Column(String, nullable=True)
    sku_id = Column(String, nullable=False)
    sku_part_number = Column(String, nullable=False)  # e.g. SPE_E3, O365_BUSINESS_PREMIUM
    friendly_name = Column(String, nullable=True)      # e.g. "Microsoft 365 Business Standard"
    assigned_date = Column(DateTime, default=datetime.utcnow)
    last_synced = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="licenses")


class TenantLicenseSummary(Base):
    """Aggregate purchased vs consumed counts per SKU per customer tenant (from /subscribedSkus)."""
    __tablename__ = "tenant_license_summary"

    id = Column(String, primary_key=True, default=gen_id)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    sku_id = Column(String, nullable=False)
    sku_part_number = Column(String, nullable=False)
    friendly_name = Column(String, nullable=True)
    enabled_units = Column(Integer, default=0)
    consumed_units = Column(Integer, default=0)
    last_synced = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Endpoint monitoring
# ---------------------------------------------------------------------------
class Endpoint(Base):
    __tablename__ = "endpoints"

    id = Column(String, primary_key=True, default=gen_id)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=False)
    hostname = Column(String, nullable=False)
    os_name = Column(String, nullable=True)
    os_version = Column(String, nullable=True)
    agent_version = Column(String, nullable=True)
    ip_address = Column(String, nullable=True)
    status = Column(Enum(EndpointStatus), default=EndpointStatus.UNKNOWN)
    last_seen = Column(DateTime, nullable=True)
    registered_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="endpoints")
    metrics = relationship("EndpointMetric", back_populates="endpoint", cascade="all, delete-orphan")


class EndpointMetric(Base):
    __tablename__ = "endpoint_metrics"

    id = Column(String, primary_key=True, default=gen_id)
    endpoint_id = Column(String, ForeignKey("endpoints.id"), nullable=False)
    cpu_percent = Column(Float, nullable=True)
    memory_percent = Column(Float, nullable=True)
    disk_percent = Column(Float, nullable=True)
    uptime_seconds = Column(Integer, nullable=True)
    disk_health_ok = Column(Boolean, default=True)
    av_enabled = Column(Boolean, nullable=True)
    pending_reboot = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    endpoint = relationship("Endpoint", back_populates="metrics")


# ---------------------------------------------------------------------------
# Integration message logs (audit trail for WhatsApp / Teams)
# ---------------------------------------------------------------------------
class WhatsAppMessage(Base):
    __tablename__ = "whatsapp_messages"

    id = Column(String, primary_key=True, default=gen_id)
    customer_id = Column(String, ForeignKey("customers.id"), nullable=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)
    wa_message_id = Column(String, nullable=True)
    from_number = Column(String, nullable=False)
    direction = Column(String, default="inbound")  # inbound | outbound
    body = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class TeamsMessage(Base):
    __tablename__ = "teams_messages"

    id = Column(String, primary_key=True, default=gen_id)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)
    channel_or_user = Column(String, nullable=True)
    direction = Column(String, default="inbound")
    body = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Email-to-ticket ingestion
# ---------------------------------------------------------------------------
class ExcludedEmailSender(Base):
    """
    A sender email address or domain pattern that should NEVER create a
    helpdesk ticket automatically - e.g. newsletters, no-reply addresses,
    or a specific person who keeps CC'ing the helpdesk by mistake.

    pattern can be:
      - an exact email address: "noreply@somevendor.com"
      - a domain wildcard: "*@spamdomain.com" (blocks the whole domain)
    Matching is case-insensitive.
    """
    __tablename__ = "excluded_email_senders"

    id = Column(String, primary_key=True, default=gen_id)
    pattern = Column(String, nullable=False, unique=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AutoReplyRule(Base):
    """
    A simple keyword-triggered canned response. If an incoming helpdesk
    email's subject or body contains ALL the words of any configured
    trigger phrase (case-insensitive, any order), the configured reply is
    sent back automatically. This is literal keyword matching, not AI -
    intentionally simple and predictable.
    """
    __tablename__ = "auto_reply_rules"

    id = Column(String, primary_key=True, default=gen_id)
    name = Column(String, nullable=False)                 # internal label, e.g. "Password reset FAQ"
    trigger_keywords = Column(String, nullable=False)      # comma-separated phrases, e.g. "password reset,forgot password"
    reply_subject = Column(String, nullable=False)
    reply_body = Column(Text, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ProcessedEmail(Base):
    """
    Tracks every inbound helpdesk email already handled, keyed by its
    Microsoft Graph message ID - so re-polling the mailbox never creates a
    duplicate ticket for the same email.
    """
    __tablename__ = "processed_emails"

    id = Column(String, primary_key=True, default=gen_id)
    graph_message_id = Column(String, nullable=False, unique=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=True)
    sender_email = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    was_excluded = Column(Boolean, default=False)
    auto_reply_sent = Column(Boolean, default=False)
    processed_at = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# OAuth token storage (Xero / Microsoft Graph)
# ---------------------------------------------------------------------------
class OAuthToken(Base):
    __tablename__ = "oauth_tokens"

    id = Column(String, primary_key=True, default=gen_id)
    provider = Column(String, nullable=False)  # "xero" | "graph"
    tenant_id = Column(String, nullable=True)  # Xero tenant / Entra tenant
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    scope = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

license_term_commitment = Column(String, default="monthly")
