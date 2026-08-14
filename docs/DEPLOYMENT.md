# Deploying the Letsma MSP Platform to Azure

This guide covers two deployment paths and everything around them (database,
secrets, custom domain, webhooks, CI/CD). Pick **Option A (container)** if you
want the more reliable, reproducible path (recommended); pick **Option B
(code-only)** if you'd rather avoid Docker entirely.

Both paths land on the same architecture:

```
Users/Webhooks (HTTPS)
        │
        ▼
Azure App Service (Linux) ── runs the FastAPI app
        │                 │
        ▼                 ▼
Azure Database for   Azure Key Vault
PostgreSQL Flexible   (secrets, read via
Server                 Managed Identity)
```

---

## 0. Prerequisites

- An Azure subscription (`az login` works).
- **Azure CLI** installed locally: `az --version` (v2.60+ recommended).
- For Option A only: **Docker Desktop** or Docker Engine running locally.
- The `msp-app/` project folder from this delivery (includes `Dockerfile`,
  `startup.sh`, and `deploy/deploy.sh` already prepared for you).

```bash
az login
az account set --subscription "<Your Subscription Name or ID>"
```

---

## Option A (recommended): One-shot scripted deployment via container

The fastest path: a ready-made script provisions everything and deploys in
one go.

```bash
cd msp-app
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

This creates, in order:
1. A **Resource Group** (`letsma-msp-rg` in `uksouth` by default - edit the
   variables at the top of the script to change region/names).
2. An **Azure Container Registry (ACR)** and builds+pushes the app's Docker
   image to it using `az acr build` (no local Docker required, actually -
   ACR Tasks builds it in the cloud).
3. An **Azure Database for PostgreSQL Flexible Server** (Burstable B1ms tier
   - fine for MVP; see §5 for scaling up) plus the `letsma_msp` database.
4. An **Azure Key Vault**, seeded with `APP-SECRET-KEY`, `DATABASE-URL`, and
   `ADMIN-PASSWORD` secrets (auto-generated, strong random values).
5. An **App Service Plan** (Linux, B1 tier) and a **Web App for Containers**
   pointing at the image in ACR.
6. A **system-assigned Managed Identity** on the Web App, granted:
   - `AcrPull` on the container registry (so it can pull the image without
     any stored credentials), and
   - `get`/`list` secret permissions on the Key Vault.
7. Core **App Settings** (`WEBSITES_PORT`, `KEY_VAULT_URL`, `BASE_URL`, and
   the Xero redirect URI), wired so the app reads everything else from Key
   Vault at startup (see `app/config.py`).

At the end it prints your live URL (`https://<name>.azurewebsites.net`) and
the exact `az keyvault secret set` commands to add your remaining
integration secrets (Xero, Microsoft Graph, WhatsApp, Teams). Run those,
then restart the app:

```bash
az webapp restart --resource-group letsma-msp-rg --name <your-webapp-name>
```

### Creating the database schema
The script provisions an *empty* Postgres database - you still need to run
the app's table creation/seed step once:

```bash
# SSH into the running container via App Service's built-in SSH support
az webapp ssh --resource-group letsma-msp-rg --name <your-webapp-name>

# Inside the container:
python -m app.seed     # creates tables + optional demo data
exit
```
(If you don't want the demo data, comment out the seed logic in
`app/seed.py` and just call `Base.metadata.create_all(bind=engine)`, or run
that one line manually via the SSH session instead.)

---

## Option B: Code-only deployment (no Docker)

If you'd rather not build a container image, App Service can deploy your
Python source directly and build it server-side with **Oryx**.

```bash
cd msp-app

# 1. Resource group + Postgres + Key Vault: reuse the same az commands as
#    steps 1, 3, and 4 in deploy/deploy.sh (skip the ACR/container steps).

# 2. Create a Linux App Service Plan + Web App with the Python runtime:
az appservice plan create \
    --resource-group letsma-msp-rg --name letsma-msp-plan \
    --is-linux --sku B1

az webapp create \
    --resource-group letsma-msp-rg --name <your-webapp-name> \
    --plan letsma-msp-plan --runtime "PYTHON:3.12"

# 3. Set the startup command to use the provided startup.sh (Gunicorn +
#    Uvicorn workers - Azure's default single-threaded dev server otherwise
#    struggles under real traffic):
az webapp config set \
    --resource-group letsma-msp-rg --name <your-webapp-name> \
    --startup-file "startup.sh"

# 4. Set the managed identity + Key Vault app settings exactly as in
#    deploy/deploy.sh steps 6-7 (skip the AcrPull role assignment - no
#    container registry is involved in this path).

# 5. Deploy your code with local Git or zip deploy:
az webapp deploy \
    --resource-group letsma-msp-rg --name <your-webapp-name> \
    --src-path . --type zip
```

Oryx automatically detects `requirements.txt` and installs it during
deployment. This path is simpler to set up but slightly less reproducible
than the container image (dependency resolution happens on Azure's build
servers rather than being baked into a versioned image).

---

## 1. Wiring up Key Vault-based secrets (both options)

`app/config.py` already contains the logic: if a `KEY_VAULT_URL` app setting
is present, it uses `DefaultAzureCredential` (which automatically picks up
the Web App's managed identity when running in Azure) to pull each secret
by name at startup, falling back to plain environment variables/`.env` if
Key Vault isn't configured (e.g. when developing locally). Nothing else in
the app needs to change.

Secret naming convention used (Key Vault names can't contain underscores):

| Key Vault secret name | Maps to |
|---|---|
| `APP-SECRET-KEY` | `APP_SECRET_KEY` |
| `DATABASE-URL` | `DATABASE_URL` |
| `ADMIN-PASSWORD` | `ADMIN_PASSWORD` |
| `GRAPH-TENANT-ID`, `GRAPH-CLIENT-ID`, `GRAPH-CLIENT-SECRET` | Microsoft Graph app credentials |
| `XERO-CLIENT-ID`, `XERO-CLIENT-SECRET` | Xero app credentials |
| `WHATSAPP-ACCESS-TOKEN`, `WHATSAPP-VERIFY-TOKEN` | WhatsApp Cloud API |
| `TEAMS-INCOMING-WEBHOOK-URL`, `TEAMS-OUTGOING-WEBHOOK-SECRET` | Teams webhooks |
| `AGENT-API-KEY` | Endpoint monitoring agent shared key |

Add or update any of them at any time with:
```bash
az keyvault secret set --vault-name <your-keyvault-name> --name XERO-CLIENT-ID --value "..."
az webapp restart --resource-group letsma-msp-rg --name <your-webapp-name>
```

---

## 2. Custom domain + HTTPS

WhatsApp and Teams webhooks require a stable HTTPS URL, and `*.azurewebsites.net`
already gives you that for free with a Microsoft-managed certificate. If you
want your own domain (e.g. `msp.letsma.co.uk`):

```bash
az webapp config hostname add \
    --resource-group letsma-msp-rg --webapp-name <your-webapp-name> \
    --hostname msp.letsma.co.uk

az webapp config ssl create \
    --resource-group letsma-msp-rg --name <your-webapp-name> \
    --hostname msp.letsma.co.uk

az webapp config ssl bind \
    --resource-group letsma-msp-rg --name <your-webapp-name> \
    --certificate-thumbprint <thumbprint-from-previous-command> \
    --ssl-type SNI
```
You'll need a CNAME/TXT record at your DNS provider pointing to
`<your-webapp-name>.azurewebsites.net` first - App Service's hostname
verification will tell you exactly what to add.

Once you have your final URL, update:
- `BASE_URL` and `XERO_REDIRECT_URI` app settings (and the redirect URI
  registered in your Xero app).
- The WhatsApp Cloud API webhook callback URL (Meta App dashboard).
- The Teams Outgoing Webhook callback URL.

---

## 3. CI/CD with GitHub Actions

The project ships with two ready-to-use workflow files - nothing to write,
just three things to configure. This is built for **Option A (container)**
deployments, matching the recommended path from §Option A above.

| File | Trigger | What it does |
|---|---|---|
| `.github/workflows/ci.yml` | Every pull request into `main` | Lints (`ruff`, advisory), byte-compiles, imports `app.main` as a smoke test, and verifies the `Dockerfile` builds. No Azure access needed - safe to run on any PR from any contributor. |
| `.github/workflows/deploy.yml` | Every push to `main` (or manual "Run workflow") | Builds the image via `az acr build`, tags it with both the commit SHA and `latest`, points the Web App at the new image, restarts it, and polls `/healthz` until it responds - failing loudly if the new revision doesn't come up healthy. |

### 3.1 One-time setup

**Step 1 - Push this repo to GitHub** (if you haven't already):
```bash
git init
git add .
git commit -m "Initial commit - Letsma MSP Platform"
git remote add origin https://github.com/<your-org>/<your-repo>.git
git push -u origin main
```

**Step 2 - Run the OIDC setup script** (uses the resource names saved by
`deploy/deploy.sh` in `.deploy-output.env`, so run this *after* deploying):
```bash
chmod +x deploy/setup-github-oidc.sh
./deploy/setup-github-oidc.sh <your-org>/<your-repo>
```
This creates an Entra ID App Registration with a **federated credential**
trusting GitHub's OIDC tokens for this specific repo (main branch pushes and
pull requests only) - **no client secret is ever generated or stored
anywhere**. It also grants that app `Contributor` on your resource group so
it can update the Web App's container image. At the end it prints exactly
what to paste into GitHub.

**Step 3 - Add the printed values in GitHub** (Settings > Secrets and
variables > Actions):

As **Secrets**:
| Name | Value |
|---|---|
| `AZURE_CLIENT_ID` | printed by the setup script |
| `AZURE_TENANT_ID` | printed by the setup script |
| `AZURE_SUBSCRIPTION_ID` | printed by the setup script |

As **Variables** (same screen, "Variables" tab - these aren't secret, just
resource names the workflow needs):
| Name | Value |
|---|---|
| `ACR_NAME` | your container registry name, e.g. `letsmamspacr12345` |
| `RESOURCE_GROUP` | `letsma-msp-rg` (or whatever you set) |
| `WEBAPP_NAME` | your web app name, e.g. `letsma-msp-67890` |

All three of these are printed at the end of `deploy/deploy.sh`, and also
saved in `.deploy-output.env` if you need to check them again later.

**Step 4 - Also create a GitHub "production" environment** (Settings >
Environments > New environment, name it `production`) if you want an extra
manual-approval gate before deploys run - `deploy.yml` already targets an
environment called `production`, so this step is optional but recommended
once real client data is involved.

### 3.2 Day-to-day usage

From here on, the workflow is just: **open a PR → CI checks run
automatically → merge to `main` → deploy runs automatically → `/healthz` is
polled to confirm the new version is actually serving traffic.** You can
also trigger a redeploy manually at any time from the Actions tab
("Run workflow" button) without needing a new commit.

To see what's currently deployed or roll back, every image is tagged with
its commit SHA in ACR - you can always point the Web App back at a previous
SHA with:
```bash
az webapp config container set \
    --resource-group letsma-msp-rg --name <your-webapp-name> \
    --docker-custom-image-name <your-acr-name>.azurecr.io/letsma-msp:<previous-commit-sha>
az webapp restart --resource-group letsma-msp-rg --name <your-webapp-name>
```

---

## 4. Deploying the endpoint monitoring agent fleet

The agent (`agent/monitor_agent.py`) just needs network access to your
Web App's public URL - it doesn't run in Azure itself. Roll it out with
whatever you already use for device management:

- **Windows (Intune/GPO)**: package as a Scheduled Task that runs every 5
  minutes: `python monitor_agent.py --heartbeat --server https://msp.letsma.co.uk`
- **Linux/macOS**: a cron entry or systemd timer with the same command.

Use a **separate `AGENT-API-KEY` per customer site** once you're managing
many clients (add more Key Vault secrets or move this table into the
database) so a compromised device at one client can't spoof data for
another.

---

## 5. Scaling up for production

| Concern | MVP default | Production recommendation |
|---|---|---|
| Database | Postgres Burstable B1ms (~£10-15/mo) | General Purpose D2ds_v5+ with zone-redundant HA |
| App Service | Linux B1 (Basic) | P1v3+ (Premium v3) with autoscale rules |
| Secrets | Key Vault + Managed Identity | Same (already production-grade) |
| Background jobs | `BackgroundTasks` in-process | Azure Service Bus queue + separate worker (Container App or Function) for WhatsApp/Teams sends, so a slow third-party API never blocks a web request |
| Auth | None on technician dashboard, path-based customer portal | Entra ID auth for technicians (`/dashboard`, `/tickets`, etc.); Entra External ID (CIAM) or magic-link tokens for `/portal/{customer_id}` |
| Monitoring | App Service default logs | Application Insights (`az monitor app-insights component create` + `APPLICATIONINSIGHTS_CONNECTION_STRING` app setting) |
| Backups | Postgres automated backups (7-35 days, on by default) | Extend retention + geo-redundant backup storage for compliance |

Resizing the existing Postgres server or App Service Plan doesn't require
re-running the whole script - just:
```bash
az postgres flexible-server update --resource-group letsma-msp-rg --name <pg-server> --sku-name Standard_D2ds_v5 --tier GeneralPurpose
az appservice plan update --resource-group letsma-msp-rg --name letsma-msp-plan --sku P1v3
```

---

## 6. Cost estimate (MVP defaults, UK South, pay-as-you-go)

| Resource | SKU | Approx. monthly cost |
|---|---|---|
| App Service Plan | Linux B1 | ~£10 |
| Postgres Flexible Server | Burstable B1ms, 32GB | ~£10-12 |
| Container Registry | Basic | ~£4 |
| Key Vault | Standard, pay-per-operation | <£1 for typical usage |
| **Total** | | **~£25-30/month** |

Prices are indicative and change over time/region - use the
[Azure Pricing Calculator](https://azure.microsoft.com/en-us/pricing/calculator/)
for a current quote before committing.

---

## 7. Teardown

To remove everything created by `deploy/deploy.sh` in one go:
```bash
az group delete --resource-group letsma-msp-rg --yes --no-wait
```
