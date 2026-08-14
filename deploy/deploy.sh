#!/bin/bash
# =============================================================================
# Letsma MSP Platform - Azure deployment script (App Service for Containers)
# =============================================================================
# This script provisions everything needed to run the app in Azure:
#   Resource Group -> ACR -> Postgres Flexible Server -> Key Vault
#   -> App Service Plan -> Web App (Linux container) -> Managed Identity wiring
#
# Prerequisites:
#   - Azure CLI installed and logged in: az login
#   - Docker installed locally (to build the image)
#
# Usage:
#   chmod +x deploy/deploy.sh
#   ./deploy/deploy.sh
#
# Safe to re-run: uses `az ... || true` idempotent patterns where sensible,
# but review before running against a production subscription.
# =============================================================================
set -euo pipefail

# ---- Configuration - edit these before running ----------------------------
RESOURCE_GROUP="letsma-msp-rg"
LOCATION="uksouth"
ACR_NAME="letsmamspacr$RANDOM"          # must be globally unique, alphanumeric only
APP_SERVICE_PLAN="letsma-msp-plan"
WEBAPP_NAME="letsma-msp-$RANDOM"        # must be globally unique -> becomes {name}.azurewebsites.net
KEYVAULT_NAME="letsma-msp-kv-$RANDOM"   # must be globally unique, 3-24 chars
PG_SERVER_NAME="letsma-msp-pg-$RANDOM"  # must be globally unique
PG_ADMIN_USER="letsmaadmin"
PG_ADMIN_PASSWORD="$(openssl rand -base64 24)"
PG_DB_NAME="letsma_msp"
SKU_APP_SERVICE="B1"                    # Basic tier - upgrade to P1v3 for production
SKU_POSTGRES="Standard_B1ms"            # Burstable - fine for MVP; use General Purpose for production

echo "=================================================================="
echo " Resource Group:     $RESOURCE_GROUP ($LOCATION)"
echo " Container Registry: $ACR_NAME"
echo " Web App:            $WEBAPP_NAME"
echo " Key Vault:           $KEYVAULT_NAME"
echo " Postgres Server:    $PG_SERVER_NAME"
echo "=================================================================="
read -p "Proceed with these settings? (y/N) " confirm
[[ "$confirm" == "y" || "$confirm" == "Y" ]] || exit 1

# ---- 1. Resource group -----------------------------------------------------
az group create --name "$RESOURCE_GROUP" --location "$LOCATION"

# ---- 2. Azure Container Registry ------------------------------------------
az acr create --resource-group "$RESOURCE_GROUP" --name "$ACR_NAME" --sku Basic --admin-enabled false

echo "Building and pushing the container image..."
az acr build --registry "$ACR_NAME" --image letsma-msp:latest --file Dockerfile .

# ---- 3. Azure Database for PostgreSQL Flexible Server ---------------------
az postgres flexible-server create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$PG_SERVER_NAME" \
    --location "$LOCATION" \
    --admin-user "$PG_ADMIN_USER" \
    --admin-password "$PG_ADMIN_PASSWORD" \
    --sku-name "$SKU_POSTGRES" \
    --tier Burstable \
    --storage-size 32 \
    --version 16 \
    --public-access 0.0.0.0-255.255.255.255   # tighten this to App Service outbound IPs in production

az postgres flexible-server db create \
    --resource-group "$RESOURCE_GROUP" \
    --server-name "$PG_SERVER_NAME" \
    --database-name "$PG_DB_NAME"

DATABASE_URL="postgresql+psycopg2://${PG_ADMIN_USER}:${PG_ADMIN_PASSWORD}@${PG_SERVER_NAME}.postgres.database.azure.com:5432/${PG_DB_NAME}?sslmode=require"

# ---- 4. Key Vault -----------------------------------------------------------
az keyvault create --resource-group "$RESOURCE_GROUP" --name "$KEYVAULT_NAME" --location "$LOCATION"

APP_SECRET_KEY="$(openssl rand -base64 32)"
az keyvault secret set --vault-name "$KEYVAULT_NAME" --name "APP-SECRET-KEY" --value "$APP_SECRET_KEY"
az keyvault secret set --vault-name "$KEYVAULT_NAME" --name "DATABASE-URL" --value "$DATABASE_URL"
az keyvault secret set --vault-name "$KEYVAULT_NAME" --name "ADMIN-PASSWORD" --value "$(openssl rand -base64 16)"

echo ""
echo "Key Vault created. Add the rest of your integration secrets now (or later):"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name XERO-CLIENT-ID --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name XERO-CLIENT-SECRET --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name GRAPH-TENANT-ID --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name GRAPH-CLIENT-ID --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name GRAPH-CLIENT-SECRET --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name WHATSAPP-ACCESS-TOKEN --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name WHATSAPP-VERIFY-TOKEN --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name TEAMS-INCOMING-WEBHOOK-URL --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name TEAMS-OUTGOING-WEBHOOK-SECRET --value <value>"
echo "  az keyvault secret set --vault-name $KEYVAULT_NAME --name AGENT-API-KEY --value <value>"
echo ""

# ---- 5. App Service Plan + Web App (Linux container) -----------------------
az appservice plan create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$APP_SERVICE_PLAN" \
    --is-linux \
    --sku "$SKU_APP_SERVICE"

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)

az webapp create \
    --resource-group "$RESOURCE_GROUP" \
    --plan "$APP_SERVICE_PLAN" \
    --name "$WEBAPP_NAME" \
    --deployment-container-image-name "${ACR_LOGIN_SERVER}/letsma-msp:latest"

# ---- 6. Managed identity: Web App -> ACR pull + Key Vault read ------------
az webapp identity assign --resource-group "$RESOURCE_GROUP" --name "$WEBAPP_NAME"
PRINCIPAL_ID=$(az webapp identity show --resource-group "$RESOURCE_GROUP" --name "$WEBAPP_NAME" --query principalId -o tsv)

ACR_ID=$(az acr show --name "$ACR_NAME" --query id -o tsv)
az role assignment create --assignee "$PRINCIPAL_ID" --scope "$ACR_ID" --role "AcrPull"

az keyvault set-policy --name "$KEYVAULT_NAME" --object-id "$PRINCIPAL_ID" --secret-permissions get list

az webapp config set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$WEBAPP_NAME" \
    --generic-configurations '{"acrUseManagedIdentityCreds": true}'

# ---- 7. App settings --------------------------------------------------------
KEYVAULT_URL="https://${KEYVAULT_NAME}.vault.azure.net/"

az webapp config appsettings set \
    --resource-group "$RESOURCE_GROUP" \
    --name "$WEBAPP_NAME" \
    --settings \
        WEBSITES_PORT=8000 \
        KEY_VAULT_URL="$KEYVAULT_URL" \
        BASE_URL="https://${WEBAPP_NAME}.azurewebsites.net" \
        XERO_REDIRECT_URI="https://${WEBAPP_NAME}.azurewebsites.net/auth/xero/callback"


# ---- 8. Persist the generated resource names for later use ----------------
# (by deploy/setup-github-oidc.sh, the GitHub Actions workflow, and you,
# 3 months from now, having forgotten what you randomly named things.)
cat > .deploy-output.env <<EOF
# Generated by deploy/deploy.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# This file is gitignored - it contains resource NAMES only, no secrets,
# but is still kept out of source control to avoid environment drift.
RESOURCE_GROUP=$RESOURCE_GROUP
LOCATION=$LOCATION
ACR_NAME=$ACR_NAME
APP_SERVICE_PLAN=$APP_SERVICE_PLAN
WEBAPP_NAME=$WEBAPP_NAME
KEYVAULT_NAME=$KEYVAULT_NAME
PG_SERVER_NAME=$PG_SERVER_NAME
PG_DB_NAME=$PG_DB_NAME
EOF

echo ""
echo "=================================================================="
echo " Deployment complete."
echo " URL:            https://${WEBAPP_NAME}.azurewebsites.net"
echo " Postgres admin: $PG_ADMIN_USER / (saved to Key Vault as ADMIN-PASSWORD; the DB password itself is embedded in DATABASE-URL)"
echo " Key Vault:      $KEYVAULT_NAME"
echo " Resource names saved to: .deploy-output.env (used by setup-github-oidc.sh)"
echo ""
echo " Next steps:"
echo "  1. Add the remaining integration secrets to Key Vault (see commands above)."
echo "  2. Restart the web app so it re-reads Key Vault: az webapp restart -g $RESOURCE_GROUP -n $WEBAPP_NAME"
echo "  3. Run the one-off seed command to create the database schema:"
echo "     az webapp ssh -g $RESOURCE_GROUP -n $WEBAPP_NAME   # then inside: python -m app.seed"
echo "  4. Update Xero/WhatsApp/Teams callback URLs to point at the BASE_URL above."
echo "  5. Run ./deploy/setup-github-oidc.sh to wire up GitHub Actions CI/CD."
echo "=================================================================="
