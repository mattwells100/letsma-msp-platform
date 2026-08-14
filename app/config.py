"""
Central configuration loader.
Reads from environment variables (populated via .env by python-dotenv).
"""
import os
from dotenv import load_dotenv

load_dotenv()


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
