"""Proactive Teams reply via Bot Framework (SingleTenant bot)."""
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Ticket


async def _get_token() -> Optional[str]:
    if not (
        settings.TEAMS_BOT_APP_ID
        and settings.TEAMS_BOT_APP_SECRET
        and settings.TEAMS_BOT_TENANT_ID
    ):
        return None

    url = (
        "https://login.microsoftonline.com/"
        f"{settings.TEAMS_BOT_TENANT_ID}/oauth2/v2.0/token"
    )
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.TEAMS_BOT_APP_ID,
        "client_secret": settings.TEAMS_BOT_APP_SECRET,
        "scope": "https://api.botframework.com/.default",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, data=data)
        resp.raise_for_status()
        return resp.json().get("access_token")


async def send_teams_reply(
    db: Session,
    ticket: Ticket,
    message: str,
    author: str = "Letsma",
) -> Optional[dict]:
    conversation_id = ticket.conversation_id
    service_url = ticket.external_ref

    if not conversation_id or not service_url:
        return None

    token = await _get_token()
    if not token:
        return None

    url = (
        f"{service_url.rstrip('/')}/v3/conversations/"
        f"{conversation_id}/activities"
    )
    body = {"type": "message", "text": message}

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=body,
        )
        resp.raise_for_status()

    ticket.updated_at = datetime.utcnow()
    db.commit()
    return {"status": resp.status_code}
