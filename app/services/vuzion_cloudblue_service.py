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


def _require_configuration() -> None:
    if not settings.VUZION_CLOUDBLUE_ENABLED:
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
) -> httpx.Response:
    _require_configuration()
    async with httpx.AsyncClient(timeout=60.0) as client:
        token = await _get_access_token(client)
        return await client.request(
            method,
            f"{settings.VUZION_CLOUDBLUE_BASE_URL.rstrip('/')}/{path.lstrip('/')}",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Subscription-Key": settings.VUZION_CLOUDBLUE_SUBSCRIPTION_KEY,
                "Content-Type": "application/json",
            },
            json=json,
        )


async def get_products() -> dict:
    """Return the configured CloudBlue product catalog."""
    response = await _authorized_request("GET", "/products")
    response.raise_for_status()
    return response.json()


async def get_customers() -> dict:
    """Return customers from the configured CloudBlue Marketplace."""
    response = await _authorized_request("GET", "/customers")
    response.raise_for_status()
    return response.json()


async def place_sales_order(payload: dict) -> dict:
    """Place a sales order only after explicit provisioning is enabled."""
    response = await _authorized_request("POST", "/orders", json=payload)
    response.raise_for_status()
    return response.json()