"""
app/services/auth_service.py

Thin wrapper around MSAL's ConfidentialClientApplication for the staff
login flow (Microsoft Entra ID SSO). Uses the OAuth2 Authorization Code
flow: the browser is redirected to Microsoft to sign in, Microsoft
redirects back to /auth/callback with a one-time code, which is then
exchanged server-side (this module) for the signed-in user's identity
claims (name, email, tenant id, object id).

msal is already an installed dependency (pulled in transitively by
azure-identity, used elsewhere for Key Vault access) - this is the first
place it's imported directly as a first-class dependency, so it's also
been added explicitly to requirements.txt.

Uses a SINGLE-TENANT app registration (letsma-msp-platform-login,
--sign-in-audience AzureADMyOrg) - the authority URL below is scoped to
Letsma's own tenant only, so Microsoft itself refuses sign-in attempts
from any other organization's accounts before this code even runs. The
id_token's "tid" claim is also explicitly re-checked in app/routers/auth.py
as defense in depth.
"""
import msal

from app.config import settings

SCOPES = ["User.Read"]


def _authority() -> str:
    return f"https://login.microsoftonline.com/{settings.AUTH_TENANT_ID}"


def build_msal_app() -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.AUTH_CLIENT_ID,
        client_credential=settings.AUTH_CLIENT_SECRET,
        authority=_authority(),
    )


def get_auth_url(state: str) -> str:
    """Builds the Microsoft login URL the browser should be redirected to."""
    app = build_msal_app()
    return app.get_authorization_request_url(
        scopes=SCOPES,
        state=state,
        redirect_uri=settings.AUTH_REDIRECT_URI,
    )


def acquire_token_by_auth_code(code: str) -> dict:
    """
    Exchanges the one-time authorization code (received at /auth/callback)
    for tokens. Returns the raw MSAL result dict - on success this
    includes "id_token_claims" (a dict with "name", "preferred_username",
    "tid", "oid", etc.); on failure it includes "error"/"error_description"
    instead. Callers should check for the "error" key rather than assume
    success.
    """
    app = build_msal_app()
    return app.acquire_token_by_authorization_code(
        code=code,
        scopes=SCOPES,
        redirect_uri=settings.AUTH_REDIRECT_URI,
    )
