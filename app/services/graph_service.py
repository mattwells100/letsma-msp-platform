"""
Microsoft Graph integration for Office 365 license management.

Uses the OAuth2 Client Credentials flow (app-only permissions) against a
single tenant. For a real multi-tenant MSP scenario, use GDAP (Granular
Delegated Admin Privileges) and repeat this per customer tenant ID, or
register a multi-tenant app and store one token per customer.tenant_id.

Required Application permissions (admin consent needed in each tenant):
  - Organization.Read.All
  - User.Read.All
  - Directory.Read.All

A friendly-name lookup table maps common Microsoft 365 SKU part numbers to
human-readable names for the dashboard.
"""
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Customer, LicenseAssignment, TenantLicenseSummary

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

SKU_FRIENDLY_NAMES = {
    "SPE_E3": "Microsoft 365 E3",
    "SPE_E5": "Microsoft 365 E5",
    "O365_BUSINESS_PREMIUM": "Microsoft 365 Business Standard",
    "SPB": "Microsoft 365 Business Premium",
    "O365_BUSINESS_ESSENTIALS": "Microsoft 365 Business Basic",
    "EXCHANGESTANDARD": "Exchange Online (Plan 1)",
    "EXCHANGEENTERPRISE": "Exchange Online (Plan 2)",
    "ATP_ENTERPRISE": "Defender for Office 365 (Plan 1)",
    "THREAT_INTELLIGENCE": "Defender for Office 365 (Plan 2)",
    "AAD_PREMIUM": "Entra ID P1",
    "AAD_PREMIUM_P2": "Entra ID P2",
}


async def _get_app_token(tenant_id: str) -> str:
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.GRAPH_CLIENT_ID,
                "client_secret": settings.GRAPH_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def sync_licenses_for_customer(db: Session, customer: Customer):
    """Pulls /subscribedSkus (tenant-wide totals) and per-user /users license
    details, storing results against the given customer record."""
    if not customer.m365_tenant_id:
        raise ValueError(f"Customer '{customer.name}' has no m365_tenant_id configured.")

    token = await _get_app_token(customer.m365_tenant_id)
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as client:
        # 1. Tenant-wide SKU totals
        sku_resp = await client.get(f"{GRAPH_BASE}/subscribedSkus", headers=headers)
        sku_resp.raise_for_status()
        skus = sku_resp.json().get("value", [])

        db.query(TenantLicenseSummary).filter_by(customer_id=customer.id).delete()
        for sku in skus:
            part_no = sku.get("skuPartNumber", "UNKNOWN")
            db.add(TenantLicenseSummary(
                customer_id=customer.id,
                sku_id=sku["skuId"],
                sku_part_number=part_no,
                friendly_name=SKU_FRIENDLY_NAMES.get(part_no, part_no),
                enabled_units=sku.get("prepaidUnits", {}).get("enabled", 0),
                consumed_units=sku.get("consumedUnits", 0),
                last_synced=datetime.utcnow(),
            ))

        # 2. Per-user assigned licenses
        users_resp = await client.get(
            f"{GRAPH_BASE}/users?$select=id,displayName,userPrincipalName,assignedLicenses&$top=999",
            headers=headers,
        )
        users_resp.raise_for_status()
        users = users_resp.json().get("value", [])

        sku_lookup = {s["skuId"]: s.get("skuPartNumber", "UNKNOWN") for s in skus}

        db.query(LicenseAssignment).filter_by(customer_id=customer.id).delete()
        for user in users:
            for lic in user.get("assignedLicenses", []):
                sku_id = lic.get("skuId")
                part_no = sku_lookup.get(sku_id, "UNKNOWN")
                db.add(LicenseAssignment(
                    customer_id=customer.id,
                    user_upn=user.get("userPrincipalName"),
                    display_name=user.get("displayName"),
                    sku_id=sku_id,
                    sku_part_number=part_no,
                    friendly_name=SKU_FRIENDLY_NAMES.get(part_no, part_no),
                    last_synced=datetime.utcnow(),
                ))

    db.commit()
    return {"skus_synced": len(skus), "users_synced": len(users)}
