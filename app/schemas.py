"""Pydantic request/response schemas."""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


# ---------------- Customers ----------------
class CustomerCreate(BaseModel):
    name: str
    trading_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    account_manager: Optional[str] = None
    whatsapp_number: Optional[str] = None
    m365_tenant_id: Optional[str] = None


class CustomerOut(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    created_at: datetime


# ---------------- Contacts ----------------
class ContactCreate(BaseModel):
    customer_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp_number: Optional[str] = None
    role: Optional[str] = None
    is_primary: bool = False


class ContactOut(ContactCreate):
    model_config = ConfigDict(from_attributes=True)
    id: str


# ---------------- Tickets ----------------
class TicketCreate(BaseModel):
    customer_id: str
    contact_id: Optional[str] = None
    subject: str
    description: Optional[str] = None
    priority: Optional[str] = "Normal"
    source: Optional[str] = "Portal"
    external_ref: Optional[str] = None


class TicketUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = None


class TicketCommentCreate(BaseModel):
    author: str
    message: str
    is_internal_note: bool = False


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    ticket_number: Optional[int]
    customer_id: str
    subject: str
    description: Optional[str]
    status: str
    priority: str
    source: str
    assigned_to: Optional[str]
    created_at: datetime
    updated_at: datetime


# ---------------- Billing ----------------
class InvoiceLineItemCreate(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float = 0.0
    account_code: str = "200"
    tax_type: str = "OUTPUT2"


class InvoiceCreate(BaseModel):
    customer_id: str
    currency: str = "GBP"
    due_date: Optional[datetime] = None
    line_items: List[InvoiceLineItemCreate]
    push_to_xero: bool = False


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    customer_id: str
    xero_invoice_id: Optional[str]
    invoice_number: Optional[str]
    status: str
    total: float
    currency: str
    issue_date: datetime
    due_date: Optional[datetime]


# ---------------- Endpoints ----------------
class EndpointRegister(BaseModel):
    customer_id: str
    hostname: str
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    agent_version: Optional[str] = None
    ip_address: Optional[str] = None


class EndpointHeartbeat(BaseModel):
    endpoint_id: str
    cpu_percent: Optional[float] = None
    memory_percent: Optional[float] = None
    disk_percent: Optional[float] = None
    uptime_seconds: Optional[int] = None
    disk_health_ok: Optional[bool] = True
    av_enabled: Optional[bool] = None
    pending_reboot: Optional[bool] = False
    ip_address: Optional[str] = None


class EndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    customer_id: str
    hostname: str
    os_name: Optional[str]
    status: str
    last_seen: Optional[datetime]
