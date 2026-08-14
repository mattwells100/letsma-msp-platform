"""
Xero integration service.

Implements the OAuth2 Authorization Code flow (with refresh tokens) and
invoice creation against the Xero Accounting API, using plain httpx calls
(no heavyweight SDK dependency).

Setup:
  1. Create an app at https://developer.xero.com/app/manage (Web app type).
  2. Set the redirect URI to match XERO_REDIRECT_URI in your .env.
  3. Copy the Client ID / Secret into .env.
  4. Visit /auth/xero/login once to complete the consent flow and store tokens.
"""
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import OAuthToken, Invoice, Customer

XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"
XERO_API_BASE = "https://api.xero.com/api.xro/2.0"


def get_authorization_url(state: str = "letsma") -> str:
    params = {
        "response_type": "code",
        "client_id": settings.XERO_CLIENT_ID,
        "redirect_uri": settings.XERO_REDIRECT_URI,
        "scope": settings.XERO_SCOPES,
        "state": state,
    }
    return f"{XERO_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_token(db: Session, code: str) -> OAuthToken:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.XERO_REDIRECT_URI,
            },
            auth=(settings.XERO_CLIENT_ID, settings.XERO_CLIENT_SECRET),
        )
        resp.raise_for_status()
        payload = resp.json()

    # Discover which Xero organisation ("tenant") the user connected
    tenant_id = None
    async with httpx.AsyncClient() as client:
        conn_resp = await client.get(
            XERO_CONNECTIONS_URL,
            headers={"Authorization": f"Bearer {payload['access_token']}"},
        )
        if conn_resp.status_code == 200 and conn_resp.json():
            tenant_id = conn_resp.json()[0]["tenantId"]

    token = db.query(OAuthToken).filter_by(provider="xero").first()
    if not token:
        token = OAuthToken(provider="xero")
        db.add(token)

    token.tenant_id = tenant_id
    token.access_token = payload["access_token"]
    token.refresh_token = payload.get("refresh_token")
    token.scope = payload.get("scope")
    token.expires_at = datetime.utcnow() + timedelta(seconds=payload.get("expires_in", 1800))
    db.commit()
    db.refresh(token)
    return token


async def _get_valid_token(db: Session) -> OAuthToken:
    token = db.query(OAuthToken).filter_by(provider="xero").first()
    if not token or not token.refresh_token:
        raise RuntimeError("Xero is not connected yet. Visit /auth/xero/login first.")

    if token.expires_at and token.expires_at > datetime.utcnow() + timedelta(seconds=60):
        return token

    # Refresh the access token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": token.refresh_token},
            auth=(settings.XERO_CLIENT_ID, settings.XERO_CLIENT_SECRET),
        )
        resp.raise_for_status()
        payload = resp.json()

    token.access_token = payload["access_token"]
    token.refresh_token = payload.get("refresh_token", token.refresh_token)
    token.expires_at = datetime.utcnow() + timedelta(seconds=payload.get("expires_in", 1800))
    db.commit()
    db.refresh(token)
    return token


async def create_invoice_in_xero(db: Session, invoice: Invoice, customer: Customer) -> dict:
    """Push a locally-created Invoice + line items to Xero as an ACCREC invoice."""
    token = await _get_valid_token(db)

    contact_payload = {"Name": customer.trading_name or customer.name}
    if customer.xero_contact_id:
        contact_payload = {"ContactID": customer.xero_contact_id}

    line_items = [
        {
            "Description": li.description,
            "Quantity": li.quantity,
            "UnitAmount": li.unit_price,
            "AccountCode": li.account_code,
            "TaxType": li.tax_type,
        }
        for li in invoice.line_items
    ]

    body = {
        "Invoices": [
            {
                "Type": "ACCREC",
                "Contact": contact_payload,
                "Date": invoice.issue_date.strftime("%Y-%m-%d"),
                "DueDate": (invoice.due_date or invoice.issue_date).strftime("%Y-%m-%d"),
                "LineItems": line_items,
                "Status": "AUTHORISED",
                "CurrencyCode": invoice.currency,
                "Reference": f"Letsma-{invoice.id[:8]}",
            }
        ]
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{XERO_API_BASE}/Invoices",
            json=body,
            headers={
                "Authorization": f"Bearer {token.access_token}",
                "Xero-Tenant-Id": token.tenant_id,
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        result = resp.json()

    xero_invoice = result["Invoices"][0]
    invoice.xero_invoice_id = xero_invoice["InvoiceID"]
    invoice.invoice_number = xero_invoice.get("InvoiceNumber")
    invoice.status = "Sent"
    db.commit()
    return xero_invoice
