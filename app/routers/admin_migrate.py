"""
A small, protected, idempotent migration endpoint that adds new columns
and tables to the live Postgres database, since there's no Alembic set up
and SSH isn't available in this container image.

Safe to call multiple times - uses "IF NOT EXISTS" throughout, so it will
never error or duplicate columns/tables on repeat calls.

Security note: this reuses AGENT_API_KEY as a simple shared-secret guard
since it already exists in Key Vault. Once Stage 1 auth (Entra ID on the
whole dashboard) is in place, this endpoint is naturally covered by that
too.
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
    """Adds the Amazon-order/time-entry/licence-pricing billing engine
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
