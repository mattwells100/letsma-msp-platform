"""Authentication for inbound Azure Bot Service activities."""

from __future__ import annotations

import time

import httpx
from fastapi import HTTPException
from jose import jwt

from app.config import settings

_OPENID_KEYS_URL = "https://login.botframework.com/v1/.well-known/keys"
_KEY_CACHE: dict = {"expires_at": 0.0, "keys": []}


async def _signing_keys() -> list[dict]:
    if _KEY_CACHE["expires_at"] > time.time():
        return _KEY_CACHE["keys"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(_OPENID_KEYS_URL)
        response.raise_for_status()
        keys = response.json().get("keys", [])

    _KEY_CACHE["keys"] = keys
    _KEY_CACHE["expires_at"] = time.time() + 3600
    return keys


async def validate_bot_framework_token(authorization: str) -> dict:
    """Validate an Azure Bot Service JWT and return its claims."""
    if not settings.TEAMS_BOT_APP_ID:
        raise HTTPException(503, "Teams Bot Framework app ID is not configured")

    scheme, _, token = (authorization or "").partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise HTTPException(401, "Missing Bot Framework bearer token")

    try:
        header = jwt.get_unverified_header(token)
        key = next(
            item for item in await _signing_keys()
            if item.get("kid") == header.get("kid")
        )
        claims = jwt.decode(
            token,
            key,
            algorithms=[header.get("alg", "RS256")],
            audience=settings.TEAMS_BOT_APP_ID,
            options={"verify_at_hash": False},
        )
        issuer = claims.get("iss")
        allowed_issuers = {
            "https://api.botframework.com",
            "https://sts.windows.net/" + settings.TEAMS_BOT_TENANT_ID + "/",
            "https://login.microsoftonline.com/" + settings.TEAMS_BOT_TENANT_ID + "/v2.0",
        }
        if issuer not in allowed_issuers:
            raise ValueError("unexpected Bot Framework token issuer")
        return claims
    except Exception as exc:
        raise HTTPException(401, "Invalid Bot Framework bearer token") from exc