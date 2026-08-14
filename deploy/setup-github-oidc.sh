#!/bin/bash
# =============================================================================
# Wires up passwordless GitHub Actions -> Azure authentication using OpenID
# Connect (OIDC) federated credentials. No client secret is ever generated,
# stored in GitHub, or rotated - GitHub's OIDC token is trusted directly by
# Entra ID for each workflow run.
#
# Run this ONCE after deploy/deploy.sh has provisioned your Azure resources
# (it reads resource names from .deploy-output.env) and after you've created
# the GitHub repository for this project.
#
# Usage:
#   chmod +x deploy/setup-github-oidc.sh
#   ./deploy/setup-github-oidc.sh <github-org-or-username>/<repo-name>
#
# Example:
#   ./deploy/setup-github-oidc.sh MattWellsLetsma/letsma-msp-platform
# =============================================================================
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <github-org-or-username>/<repo-name>"
    echo "Example: $0 MattWellsLetsma/letsma-msp-platform"
    exit 1
fi
GH_REPO="$1"

if [[ ! -f ".deploy-output.env" ]]; then
    echo "ERROR: .deploy-output.env not found. Run deploy/deploy.sh first, or"
    echo "create this file manually with RESOURCE_GROUP and ACR_NAME set."
    exit 1
fi
source .deploy-output.env

APP_NAME="letsma-msp-github-actions"

echo "=================================================================="
echo " GitHub repo:      $GH_REPO"
echo " Resource group:   $RESOURCE_GROUP"
echo " Entra app name:   $APP_NAME"
echo "=================================================================="

# ---- 1. Create (or reuse) an Entra ID App Registration --------------------
EXISTING_APP_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)
if [[ -n "$EXISTING_APP_ID" ]]; then
    echo "Reusing existing app registration: $EXISTING_APP_ID"
    APP_ID="$EXISTING_APP_ID"
else
    APP_ID=$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)
    echo "Created app registration: $APP_ID"
fi

# ---- 2. Create a service principal for the app (if not already present) --
az ad sp create --id "$APP_ID" >/dev/null 2>&1 || echo "Service principal already exists."
SP_OBJECT_ID=$(az ad sp show --id "$APP_ID" --query id -o tsv)

# ---- 3. Grant Contributor on the resource group ---------------------------
SUBSCRIPTION_ID=$(az account show --query id -o tsv)
az role assignment create \
    --assignee-object-id "$SP_OBJECT_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Contributor" \
    --scope "/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}" \
    2>/dev/null || echo "Role assignment already exists (or you lack permission - check manually)."

# ---- 4. Federated credentials: trust GitHub OIDC tokens for this repo -----
# One for the main branch (used by the deploy workflow), one for pull_request
# (harmless to add - lets you extend the workflow to PR-triggered dry-runs
# later without another manual step).
create_federated_cred() {
    local subject="$1"
    local cred_name="$2"
    az ad app federated-credential create \
        --id "$APP_ID" \
        --parameters "{
            \"name\": \"${cred_name}\",
            \"issuer\": \"https://token.actions.githubusercontent.com\",
            \"subject\": \"${subject}\",
            \"audiences\": [\"api://AzureADTokenExchange\"]
        }" 2>/dev/null || echo "Federated credential '${cred_name}' already exists - skipping."
}

create_federated_cred "repo:${GH_REPO}:ref:refs/heads/main" "letsma-msp-main-branch"
create_federated_cred "repo:${GH_REPO}:pull_request" "letsma-msp-pull-requests"

TENANT_ID=$(az account show --query tenantId -o tsv)

echo ""
echo "=================================================================="
echo " Setup complete. Add these as GitHub repository secrets:"
echo " (Settings > Secrets and variables > Actions > New repository secret)"
echo ""
echo "   AZURE_CLIENT_ID       = $APP_ID"
echo "   AZURE_TENANT_ID       = $TENANT_ID"
echo "   AZURE_SUBSCRIPTION_ID = $SUBSCRIPTION_ID"
echo ""
echo " No client secret is needed or generated - authentication happens via"
echo " OIDC federated identity, scoped only to pushes/PRs on repo '$GH_REPO'."
echo ""
echo " The workflow file at .github/workflows/deploy.yml already references"
echo " these three secret names, along with your ACR/Web App names:"
echo "   ACR_NAME    = $ACR_NAME"
echo "   WEBAPP_NAME = $WEBAPP_NAME"
echo " -> add these two as repository VARIABLES (not secrets, they're just"
echo "    names) at Settings > Secrets and variables > Actions > Variables."
echo "=================================================================="
