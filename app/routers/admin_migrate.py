"""
A small, protected, idempotent set of migration endpoints that add new
columns and tables to the live Postgres database, since there's no
Alembic set up and SSH isn't available in this container image.

Safe to call multiple times - uses "IF NOT EXISTS" throughout, so it will
never error or duplicate columns/tables on repeat calls.

Security note: this reuses AGENT_API_KEY as a simple shared-secret guard
since it already exists in Key Vault. Once Stage 1 auth (Entra ID on the
whole dashboard) is in place, these endpoints are naturally covered by
that too.
"""
from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

router = APIRouter(prefix="/api/admin", tags=["Admin - Schema Migration"])


def _check_admin_key(x_agent_key: str = Header(default="")):
    if x_agent_key != settings.AGENT_API_KEY:
        raise HTTPException(401, "Invalid admin key")


@router.post("/migrate-contacts-schema")
def migrate_contacts_schema(db: Session = Depends(get_db), _=Depends(_check_admin_key)):
    """Adds the Microsoft 365 contact-sync columns to the contacts table."""
    statements = [
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS first_name VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_name VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS business_phone VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS mobile_phone VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS graph_user_id VARCHAR",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'manual'",
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_synced_from_graph TIMESTAMP",
    ]
    applied = []
    for stmt in statements:
        db.execute(text(stmt))
        applied.append(stmt)
    db.commit()
    return {"ok": True, "statements_applied": applied}


@router.post("/migrate-billing-schema")
def migrate_billing_schema(db: Session = Depends(get_db), _=Depends(_check_admin_key)):
    """Adds the purchasing/time-entry/licence-pricing billing engine
    columns and tables (Customer billing config, Invoice billing-period
    columns, and the new TimeEntry / AmazonOrder / AmazonOrderLineItem /
    LicensePrice tables)."""
    statements = [
        # New columns on the existing customers table
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS billing_type VARCHAR DEFAULT 'payg'",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS monthly_support_fee FLOAT DEFAULT 0.0",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS payg_hourly_rate FLOAT DEFAULT 0.0",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS amazon_markup_percent FLOAT DEFAULT 0.0",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS license_billing_mode VARCHAR DEFAULT 'none'",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS licensed_skus_billed VARCHAR",

        # New columns on the existing invoices table (double-billing prevention)
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS billing_period_start TIMESTAMP",
        "ALTER TABLE invoices ADD COLUMN IF NOT EXISTS billing_period_end TIMESTAMP",

        # Brand new tables
        """CREATE TABLE IF NOT EXISTS time_entries (
            id VARCHAR PRIMARY KEY,
            ticket_id VARCHAR REFERENCES tickets(id),
            customer_id VARCHAR NOT NULL REFERENCES customers(id),
            technician_name VARCHAR,
            work_date TIMESTAMP,
            hours FLOAT NOT NULL,
            description TEXT,
            billable BOOLEAN DEFAULT TRUE,
            hourly_rate_override FLOAT,
            invoiced BOOLEAN DEFAULT FALSE,
            invoice_id VARCHAR REFERENCES invoices(id),
            created_at TIMESTAMP DEFAULT NOW()
        )""",

        """CREATE TABLE IF NOT EXISTS amazon_orders (
            id VARCHAR PRIMARY KEY,
            amazon_order_id VARCHAR NOT NULL UNIQUE,
            customer_id VARCHAR REFERENCES customers(id),
            order_date TIMESTAMP,
            total FLOAT DEFAULT 0.0,
            currency VARCHAR DEFAULT 'GBP',
            description TEXT,
            source VARCHAR DEFAULT 'csv_import',
            invoiced BOOLEAN DEFAULT FALSE,
            invoice_id VARCHAR REFERENCES invoices(id),
            imported_at TIMESTAMP DEFAULT NOW()
        )""",

        """CREATE TABLE IF NOT EXISTS amazon_order_line_items (
            id VARCHAR PRIMARY KEY,
            order_id VARCHAR NOT NULL REFERENCES amazon_orders(id),
            description VARCHAR NOT NULL,
            quantity FLOAT DEFAULT 1.0,
            unit_price FLOAT DEFAULT 0.0
        )""",

        """CREATE TABLE IF NOT EXISTS license_prices (
            id VARCHAR PRIMARY KEY,
            customer_id VARCHAR REFERENCES customers(id),
            sku_part_number VARCHAR NOT NULL,
            monthly_unit_price FLOAT DEFAULT 0.0
        )""",
    ]
    applied = []
    for stmt in statements:
        db.execute(text(stmt))
        applied.append(stmt)
    db.commit()
    return {"ok": True, "statements_applied": applied}


@router.post("/migrate-email-ticket-schema")
def migrate_email_ticket_schema(db: Session = Depends(get_db), _=Depends(_check_admin_key)):
    """Adds the email-to-ticket ingestion tables (excluded senders,
    auto-reply rules, processed-email dedup tracking)."""
    statements = [
        """CREATE TABLE IF NOT EXISTS excluded_email_senders (
            id VARCHAR PRIMARY KEY,
            pattern VARCHAR NOT NULL UNIQUE,
            reason VARCHAR,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS auto_reply_rules (
            id VARCHAR PRIMARY KEY,
            name VARCHAR NOT NULL,
            trigger_keywords VARCHAR NOT NULL,
            reply_subject VARCHAR NOT NULL,
            reply_body TEXT NOT NULL,
            active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT NOW()
        )""",
        """CREATE TABLE IF NOT EXISTS processed_emails (
            id VARCHAR PRIMARY KEY,
            graph_message_id VARCHAR NOT NULL UNIQUE,
            ticket_id VARCHAR REFERENCES tickets(id),
            sender_email VARCHAR,
            subject VARCHAR,
            was_excluded BOOLEAN DEFAULT FALSE,
            auto_reply_sent BOOLEAN DEFAULT FALSE,
            processed_at TIMESTAMP DEFAULT NOW()
        )""",
    ]
    applied = []
    for stmt in statements:
        db.execute(text(stmt))
        applied.append(stmt)
    db.commit()
    return {"ok": True, "statements_applied": applied}


@router.post("/migrate-purchasing-schema")
def migrate_purchasing_schema(db: Session = Depends(get_db), _=Depends(_check_admin_key)):
    """
    Adds the general purchasing module + license profitability columns:
      - amazon_orders.supplier: identifies which supplier an order is
        from (Amazon, CDW, Ingram Micro, etc.), defaulting existing rows
        to 'Amazon' so nothing about current Amazon CSV import behaviour
        changes.
      - license_prices.cost_price: what Letsma pays for a licence SKU
        (e.g. CSP cost), separate from monthly_unit_price (what the
        customer is charged) - used purely for profitability reporting,
        never billed to customers.
    """
    statements = [
        "ALTER TABLE amazon_orders ADD COLUMN IF NOT EXISTS supplier VARCHAR DEFAULT 'Amazon'",
        "UPDATE amazon_orders SET supplier = 'Amazon' WHERE supplier IS NULL",
        "ALTER TABLE license_prices ADD COLUMN IF NOT EXISTS cost_price FLOAT DEFAULT 0.0",
    ]
    applied = []
    for stmt in statements:
        db.execute(text(stmt))
        applied.append(stmt)
    db.commit()
    return {"ok": True, "statements_applied": applied}
