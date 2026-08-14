# Letsma MSP Platform

A unified web application for running Letsma's managed service business:
**customer management**, **billing (Xero)**, **Microsoft 365 license management**,
a **helpdesk** with automatic ticket logging from **WhatsApp Business** and
**Microsoft Teams**, a lightweight **customer self-service portal**, and an
**endpoint monitoring agent**.

Built with Python (FastAPI + SQLAlchemy + Jinja2/Bootstrap) so it runs
anywhere with zero paid infrastructure to start (SQLite by default; swap in
Postgres for production by changing one connection string).

---

## 1. What's included

| Module | What it does |
|---|---|
| **Customers** | CRUD for customer accounts, contacts, WhatsApp numbers, and linked M365 tenant ID |
| **Helpdesk** | Multi-channel ticketing (Portal, Email-ready, WhatsApp, Teams, Phone, Endpoint Alerts), SLA due-dates by priority, comments/internal notes, status workflow |
| **Billing** | Draft invoices locally, then push to **Xero** as real ACCREC invoices via OAuth2 |
| **O365 Licensing** | Syncs tenant-wide SKU totals and per-user license assignments from **Microsoft Graph** |
| **WhatsApp** | Meta Cloud API webhook: inbound customer messages auto-create/append helpdesk tickets; outbound status updates sent back to the customer |
| **Teams** | Incoming Webhook posts Adaptive Card notifications for new tickets/endpoint alerts to a channel; Outgoing Webhook lets technicians log tickets straight from a Teams channel |
| **Endpoint monitoring** | A standalone Python agent (`agent/monitor_agent.py`) reports CPU/RAM/disk/AV/reboot-pending status; the platform flags endpoints Online/Warning/Offline and raises Teams alerts automatically |
| **Customer Portal** | Simple external page per customer to raise tickets and view invoice status |

---

## 2. Quick start (local demo)

```bash
cd msp-app
python3 -m venv venv && source venv/bin/activate      # optional but recommended
pip install -r requirements.txt

cp .env.example .env                                   # fill in real values later
python3 -m app.seed                                     # creates DB + demo data
uvicorn app.main:app --reload --port 8000
```

Then open:
- **Dashboard**: http://localhost:8000/dashboard
- **API docs (Swagger)**: http://localhost:8000/docs
- **Customer self-service portal**: http://localhost:8000/portal/{customer_id}

The demo seed creates two sample customers ("The Officers Mess", "The Mary
Woolstonecraft"), sample tickets, an invoice, and two endpoints so the UI
isn't empty on first run.

---

## 3. Connecting the real integrations

### 3.1 Xero (invoicing)
1. Create an app at https://developer.xero.com/app/manage (type: **Web app**).
2. Set the redirect URI to `{BASE_URL}/auth/xero/callback` (must match `.env` exactly).
3. Copy the **Client ID** / **Client Secret** into `.env`.
4. Start the app, then visit `/auth/xero/login` once in a browser and approve
   access to your Xero organisation. Tokens (with auto-refresh) are stored in
   the `oauth_tokens` table from then on.
5. From the Billing page, "Push to Xero" will create a real `ACCREC` invoice.

### 3.2 Microsoft 365 licensing (Microsoft Graph)
1. In **Entra ID admin center** > App registrations, create an app.
2. Add **Application permissions**: `Organization.Read.All`, `User.Read.All`,
   `Directory.Read.All`, and grant admin consent (in each customer tenant you
   manage, or via GDAP/Partner Center for multi-tenant MSP access).
3. Put the Tenant ID / Client ID / Client Secret in `.env`.
4. On each **Customer** record, set `m365_tenant_id` to that customer's Entra
   tenant ID, then click **"Sync M365 Licenses"** on their customer page.

> For true multi-tenant MSP scale, replace the single client-credentials flow
> in `app/services/graph_service.py` with **GDAP** delegated admin relationships
> per customer, or a multi-tenant app registration with per-tenant consent.

### 3.3 WhatsApp Business (Meta Cloud API)
1. Create a Meta App at https://developers.facebook.com/apps and add the
   **WhatsApp** product.
2. Under WhatsApp > Configuration, set the **Callback URL** to
   `{BASE_URL}/webhooks/whatsapp` and the **Verify Token** to match
   `WHATSAPP_VERIFY_TOKEN` in `.env`. Subscribe to the `messages` field.
3. Generate a permanent **System User access token** and note the **Phone
   Number ID** - put both in `.env`.
4. Set each customer's `whatsapp_number` (or a contact's `whatsapp_number`)
   to the E.164 number (no `+`) they message you from, so inbound messages
   are matched to the right account automatically.

### 3.4 Microsoft Teams
- **Outbound notifications**: In the target channel, add the **Incoming
  Webhook** connector and paste the URL into `TEAMS_INCOMING_WEBHOOK_URL`.
  New tickets and endpoint alerts will post as Adaptive Cards automatically.
- **Inbound ticket logging**: In the same channel, add an **Outgoing
  Webhook**, point its callback URL at `{BASE_URL}/webhooks/teams`, and copy
  the generated HMAC security token into `TEAMS_OUTGOING_WEBHOOK_SECRET`.
  Technicians can then @mention the bot with a message like:
  `@Letsma Bot New ticket: printer down at Reception for The Officers Mess`
  and a ticket is created and routed to the matching customer automatically.

  > For a full interactive bot (buttons, adaptive card forms, proactive 1:1
  > messages) migrate `app/services/teams_service.py` to the **Bot Framework
  > SDK** registered via **Azure Bot Service** - the webhook approach here is
  > intentionally dependency-light for a fast MVP.

### 3.5 Endpoint monitoring agent
```bash
# One-time registration on each managed device:
python agent/monitor_agent.py --register --customer-id <ID> --server https://msp.letsma.co.uk

# Recurring heartbeat (schedule every 5 minutes):
python agent/monitor_agent.py --heartbeat --server https://msp.letsma.co.uk
```
- **Windows**: create a Scheduled Task (Trigger: repeat every 5 minutes).
- **Linux/macOS**: cron entry, e.g. `*/5 * * * * python3 /opt/letsma-agent/monitor_agent.py --heartbeat --server ...`

The agent checks CPU/RAM/disk usage, disk SMART health, Windows Defender
status, and pending-reboot state, and raises a Teams alert automatically if
any threshold is breached or the device stops checking in
(`AGENT_OFFLINE_THRESHOLD_MINUTES` in `.env`).

---

## 4. Project structure

```
msp-app/
├── app/
│   ├── main.py                 # FastAPI app + router registration
│   ├── config.py                # env-based settings (+ optional Key Vault lookup)
│   ├── database.py, models.py, schemas.py
│   ├── seed.py                  # demo data generator
│   ├── routers/                 # customers, tickets, billing, licenses, endpoints,
│   │                             # webhooks_whatsapp, webhooks_teams, auth_xero, portal
│   ├── services/                 # xero_service, whatsapp_service, teams_service,
│   │                             # graph_service, security, ticket_numbering
│   ├── templates/                # Jinja2 + Bootstrap portal pages
│   └── static/style.css          # Letsma navy/orange branding
├── agent/monitor_agent.py       # standalone endpoint monitoring agent
├── .github/workflows/
│   ├── ci.yml                    # lint + smoke-test every pull request
│   └── deploy.yml                # build & deploy to Azure on every push to main
├── deploy/
│   ├── deploy.sh                 # one-shot Azure resource provisioning + first deploy
│   └── setup-github-oidc.sh      # one-shot passwordless GitHub Actions <-> Azure wiring
├── docs/
│   ├── ARCHITECTURE.md           # system design, data flow, roadmap
│   └── DEPLOYMENT.md             # full Azure deployment + CI/CD guide
├── Dockerfile, .dockerignore     # container image definition (Option A deployment)
├── startup.sh                    # Gunicorn/Uvicorn startup command (Option B deployment)
├── requirements.txt
├── .gitignore
└── .env.example
```

---

## 5. Production hardening checklist

This is a fully working MVP; before going live with real customer data,
you should:
- Switch `DATABASE_URL` to **PostgreSQL** (e.g. Azure Database for PostgreSQL).
- Put the app behind **Entra ID (Azure AD) auth** for technicians and
  **Entra External ID (CIAM)** or magic-link tokens for the customer portal,
  rather than the plain path-based `/portal/{customer_id}` used in the MVP.
- Move background alerting/sync (`APScheduler` is already a dependency) into
  a proper scheduled job for periodic license syncs and offline-endpoint
  sweeps rather than only computing status at page-load time.
- Add rate limiting + signature validation hardening on all public webhook
  routes (`/webhooks/whatsapp`, `/webhooks/teams`).
- Store secrets in **Azure Key Vault** instead of a local `.env` file.
- Add automated backups for the database and the `oauth_tokens` table.

See `docs/ARCHITECTURE.md` for the full system design, and
**`docs/DEPLOYMENT.md` for a complete, copy-paste Azure deployment guide**
(including a one-shot `deploy/deploy.sh` script that provisions App Service,
PostgreSQL, Container Registry, and Key Vault with Managed Identity wiring).

**CI/CD** is included out of the box: `.github/workflows/ci.yml` lints and
smoke-tests every pull request, and `.github/workflows/deploy.yml`
automatically builds and deploys to Azure on every push to `main` using
passwordless OIDC login (`deploy/setup-github-oidc.sh` sets this up in one
command). See §3 of `docs/DEPLOYMENT.md` for the one-time setup steps.
