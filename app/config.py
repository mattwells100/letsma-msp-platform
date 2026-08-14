"""
Central configuration loader.

Reads from environment variables (populated via .env locally by
python-dotenv). In Azure, if a KEY_VAULT_URL app setting is present, secret
values are instead pulled from Azure Key Vault at startup using the App
Service's managed identity (no credentials stored anywhere) - see
docs/DEPLOYMENT.md for setup. Any Key Vault secret found simply overrides
the corresponding environment variable of the same name (with '-' instead
of '_', since Key Vault secret names can't contain underscores).
"""
import os
from dotenv import load_dotenv

load_dotenv()

KEY_VAULT_URL = os.getenv("KEY_VAULT_URL", "")

_SECRET_NAMES = [
    "APP-SECRET-KEY", "DATABASE-URL", "ADMIN-PASSWORD",
    "GRAPH-CLIENT-ID", "GRAPH-CLIENT-SECRET", "GRAPH-TENANT-ID",
    "XERO-CLIENT-ID", "XERO-CLIENT-SECRET",
    "WHATSAPP-ACCESS-TOKEN", "WHATSAPP-VERIFY-TOKEN",
    "TEAMS-INCOMING-WEBHOOK-URL", "TEAMS-OUTGOING-WEBHOOK-SECRET",
    "AGENT-API-KEY",
]

if KEY_VAULT_URL:
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient

        _credential = DefaultAzureCredential()
        _kv_client = SecretClient(vault_url=KEY_VAULT_URL, credential=_credential)
        for secret_name in _SECRET_NAMES:
            try:
                value = _kv_client.get_secret(secret_name).value
                os.environ[secret_name.replace("-", "_")] = value
            except Exception:
                pass  # secret not set in this Key Vault - fall back to env/.env default
    except Exception as e:
        print(f"WARNING: Key Vault lookup skipped ({e}). Falling back to environment variables.")


class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "Letsma MSP Platform")
    SECRET_KEY: str = os.getenv("APP_SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./letsma_msp.db")
    ADMIN_EMAIL: str = os.getenv("ADMIN_EMAIL", "admin@letsma.co.uk")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "ChangeMe123!")
    BASE_URL: str = os.getenv("BASE_URL", "http://localhost:8000")

    # Microsoft Graph / Entra ID
    GRAPH_TENANT_ID: str = os.getenv("GRAPH_TENANT_ID", "")
    GRAPH_CLIENT_ID: str = os.getenv("GRAPH_CLIENT_ID", "")
    GRAPH_CLIENT_SECRET: str = os.getenv("GRAPH_CLIENT_SECRET", "")

    # Xero
    XERO_CLIENT_ID: str = os.getenv("XERO_CLIENT_ID", "")
    XERO_CLIENT_SECRET: str = os.getenv("XERO_CLIENT_SECRET", "")
    XERO_REDIRECT_URI: str = os.getenv("XERO_REDIRECT_URI", "http://localhost:8000/auth/xero/callback")
    XERO_SCOPES: str = os.getenv("XERO_SCOPES", "offline_access accounting.transactions accounting.contacts accounting.settings")

    # WhatsApp
    WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "letsma-verify-token")
    WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")

    # Teams
    TEAMS_INCOMING_WEBHOOK_URL: str = os.getenv("TEAMS_INCOMING_WEBHOOK_URL", "")
    TEAMS_OUTGOING_WEBHOOK_SECRET: str = os.getenv("TEAMS_OUTGOING_WEBHOOK_SECRET", "")

    # Agent
    AGENT_API_KEY: str = os.getenv("AGENT_API_KEY", "letsma-agent-shared-key")
    AGENT_OFFLINE_THRESHOLD_MINUTES: int = int(os.getenv("AGENT_OFFLINE_THRESHOLD_MINUTES", "15"))


settings = Settings()
