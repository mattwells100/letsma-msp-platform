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


async def get_products() -> dict:
    """Return the configured CloudBlue product catalog."""
    _require_configuration()
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{settings.VUZION_CLOUDBLUE_BASE_URL.rstrip('/')}/products",
            auth=(settings.VUZION_CLOUDBLUE_USERNAME, settings.VUZION_CLOUDBLUE_PASSWORD),
            headers={"X-Subscription-Key": settings.VUZION_CLOUDBLUE_SUBSCRIPTION_KEY},
        )
        response.raise_for_status()
        return response.json()


async def place_sales_order(payload: dict) -> dict:
    """Place a sales order only after explicit provisioning is enabled."""
    _require_configuration()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{settings.VUZION_CLOUDBLUE_BASE_URL.rstrip('/')}/orders",
            auth=(settings.VUZION_CLOUDBLUE_USERNAME, settings.VUZION_CLOUDBLUE_PASSWORD),
            headers={
                "X-Subscription-Key": settings.VUZION_CLOUDBLUE_SUBSCRIPTION_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()