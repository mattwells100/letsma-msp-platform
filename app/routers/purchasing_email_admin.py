"""
app/routers/purchasing_email_admin.py

Admin/migration endpoint for the purchasing-email-ingest feature. Follows
the same X-Agent-Key admin pattern already used by endpoints like
/api/admin/migrate-billing-schema and /api/admin/migrate-price-term-schema.

  POST /api/admin/migrate-purchasing-email-schema
      One-off migration: adds the new columns on `amazon_orders` and the
      new `processed_purchase_emails` dedup table needed for email
      ingest. Safe to re-run (every statement checks IF NOT EXISTS).

Note: ids throughout this codebase are plain application-generated UUID
strings (models.gen_id() -> str(uuid.uuid4())), NOT Postgres-native UUID
columns with a server-side default - so the new table's id column below
is a plain VARCHAR primary key with no DB-side default, matching every
other table in models.py (populated by SQLAlchemy at insert time instead).
"""
import os

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import text

from app.database import engine

router = APIRouter()


def _check_agent_key(x_agent_key: str = None):
    expected = os.environ.get("AGENT_API_KEY")
    if not expected or x_agent_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Agent-Key")


@router.post("/api/admin/migrate-purchasing-email-schema")
def migrate_purchasing_email_schema(x_agent_key: str = Header(None)):
    _check_agent_key(x_agent_key)

    statements = [
        # New columns on the existing amazon_orders table (your general
        # purchasing table - see the AmazonOrder docstring in models.py).
        "ALTER TABLE amazon_orders ADD COLUMN IF NOT EXISTS extraction_status VARCHAR NOT NULL DEFAULT 'confirmed';",
        "ALTER TABLE amazon_orders ADD COLUMN IF NOT EXISTS raw_extraction_json TEXT;",
        "ALTER TABLE amazon_orders ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMP;",
        "ALTER TABLE amazon_orders ADD COLUMN IF NOT EXISTS end_user_hint VARCHAR;",
        # Helper index for the secondary dedup check (same supplier +
        # order reference re-sent under a different email).
        "CREATE INDEX IF NOT EXISTS ix_amazon_orders_supplier_order_id "
        "ON amazon_orders (supplier, amazon_order_id);",
        # Per-email dedup table, mirroring the existing processed_emails
        # table used by the helpdesk email-to-ticket feature.
        """
        CREATE TABLE IF NOT EXISTS processed_purchase_emails (
            id VARCHAR PRIMARY KEY,
            graph_message_id VARCHAR UNIQUE NOT NULL,
            order_id VARCHAR REFERENCES amazon_orders(id),
            subject VARCHAR,
            processed_at TIMESTAMP DEFAULT now()
        );
        """,
    ]

    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))

    return {"status": "ok", "statements_run": len(statements)}
