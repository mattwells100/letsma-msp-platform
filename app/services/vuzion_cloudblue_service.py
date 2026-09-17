"""Safe client boundary for Vuzion/Infinigate CloudBlue Simple API.

This module deliberately does not place orders automatically. Product MPNs,
CloudBlue customer IDs, and credentials must be configured and reviewed before
provisioning is enabled.
"""
from __future__ import annotations

import httpx

from app.config import settings


class VuzionCloudBlueNotConfigured(RuntimeError):
    pass


def _require_configuration(*, require_provisioning: bool = False) -> None:
    if require_provisioning and not settings.VUZION_CLOUDBLUE_ENABLED:
        raise VuzionCloudBlueNotConfigured("Vuzion CloudBlue provisioning is disabled")
    if not (
        settings.VUZION_CLOUDBLUE_BASE_URL
        and settings.VUZION_CLOUDBLUE_SUBSCRIPTION_KEY
        and settings.VUZION_CLOUDBLUE_USERNAME
        and settings.VUZION_CLOUDBLUE_PASSWORD
    ):
        raise VuzionCloudBlueNotConfigured("Vuzion CloudBlue credentials are incomplete")


async def _get_access_token(client: httpx.AsyncClient) -> str:
    """Authenticate against the Marketplace API token endpoint."""
    response = await client.post(
        f"{settings.VUZION_CLOUDBLUE_BASE_URL.rstrip('/')}/token",
        auth=(settings.VUZION_CLOUDBLUE_USERNAME, settings.VUZION_CLOUDBLUE_PASSWORD),
        headers={
            "Content-Type": "application/json",
            "X-Subscription-Key": settings.VUZION_CLOUDBLUE_SUBSCRIPTION_KEY,
        },
        json={"marketplace": settings.VUZION_CLOUDBLUE_MARKETPLACE},
    )
    response.raise_for_status()
    response_data = response.json()
    token = (
        response_data.get("access_token")
        or response_data.get("token")
        or response_data.get("bearer_token")
        or response_data.get("id_token")
    )
    if not token:
        raise RuntimeError("Vuzion CloudBlue authentication returned no bearer token")
    return token


async def _authorized_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    require_provisioning: bool = False,
) -> httpx.Response:
    _require_configuration(require_provisioning=require_provisioning)
    async with httpx.AsyncClient(timeout=15.0) as client:
        token = await _get_access_token(client)
        return await client.request(
            method,
            f"{settings.VUZION_CLOUDBLUE_BASE_URL.rstrip('/')}/{path.lstrip('/')}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Subscription-Key": settings.VUZION_CLOUDBLUE_SUBSCRIPTION_KEY,
                "Content-Type": "application/json",
            },
            params=params,
            json=json,
        )


async def get_products() -> dict:
    """Return the configured CloudBlue product catalog."""
    response = await _authorized_request("GET", "/products")
    response.raise_for_status()
    return response.json()


async def get_customers() -> dict:
    """Return all customers from the paginated CloudBlue Marketplace endpoint."""
    response = await _authorized_request("GET", "/customers")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return payload

    customers = list(payload["data"])
    pagination = payload.get("pagination") or {}
    total = pagination.get("total")
    offset = int(pagination.get("offset") or 0)
    limit = int(pagination.get("limit") or len(customers) or 10)

    # CloudBlue uses offset/limit pagination. Continue until the reported
    # total is loaded or a repeated/empty page proves there are no more rows.
    offset += limit
    while total is None or offset < int(total):
        next_response = await _authorized_request(
            "GET", "/customers", params={"offset": offset, "limit": limit}
        )
        next_response.raise_for_status()
        next_payload = next_response.json()
        next_data = next_payload.get("data", []) if isinstance(next_payload, dict) else []
        if not next_data:
            break
        existing_ids = {str(customer.get("id")) for customer in customers if isinstance(customer, dict)}
        new_customers = [
            customer for customer in next_data
            if not isinstance(customer, dict) or str(customer.get("id")) not in existing_ids
        ]
        if not new_customers:
            break
        customers.extend(new_customers)
        offset += limit

    payload["data"] = customers
    if isinstance(pagination, dict):
        pagination["loadedCount"] = len(customers)
        payload["pagination"] = pagination
    return payload


async def get_subscriptions(cloudblue_customer_id: str) -> dict:
    """Return active CloudBlue subscriptions for one Marketplace customer."""
    response = await _authorized_request(
        "GET",
        "/subscriptions",
        params={"customerId": cloudblue_customer_id, "status": "active"},
    )
    response.raise_for_status()
    payload = response.json()
    records = payload.get("data", []) if isinstance(payload, dict) else payload
    if records:
        return payload

    # Some Marketplace accounts use a different status spelling. Retry without
    # the status filter and let the normalizer expose the returned subscriptions.
    fallback = await _authorized_request(
        "GET",
        "/subscriptions",
        params={"customerId": cloudblue_customer_id},
    )
    fallback.raise_for_status()
    return fallback.json()


async def get_service_plan(plan_id: str) -> dict:
    """Return the CloudBlue service plan used by a subscription."""
    response = await _authorized_request("GET", f"/plans/{plan_id}")
    response.raise_for_status()
    return response.json()


async def place_sales_order(payload: dict) -> dict:
    """Place a sales order only after explicit provisioning is enabled."""
    response = await _authorized_request(
        "POST",
        "/orders",
        json=payload,
        require_provisioning=True,
    )
    response.raise_for_status()
    return response.json()


async def estimate_sales_order(payload: dict) -> dict:
    """Estimate a licence change without placing an order."""
    response = await _authorized_request("POST", "/orders/estimate", json=payload)
    response.raise_for_status()
    return response.json()