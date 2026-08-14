# Letsma MSP Platform - Architecture

## 1. High-level system diagram

```
                         ┌───────────────────────────────────────┐
                         │            Letsma MSP Platform          │
                         │              (FastAPI app)              │
                         │                                          │
   Technicians  ───────► │  Dashboard / Customers / Tickets /       │
   (browser)              │  Billing / Licenses / Endpoints (Jinja)  │
                         │                                          │
   Customers   ───────► │  Self-service Portal (/portal/{id})       │
   (browser)              │                                          │
                         │            ┌─────────────┐                │
                         │            │  REST API    │                │
                         │            │  /api/*      │                │
                         │            └──────┬───────┘                │
                         │                    │                        │
                         │   ┌────────────────┼─────────────────┐      │
                         │   │        SQLAlchemy ORM              │      │
                         │   │  Customers·Tickets·Invoices·        │      │
                         │   │  Licenses·Endpoints·OAuthTokens     │      │
                         │   └────────────────┬─────────────────┘      │
                         │                    │                        │
                         │              SQLite / PostgreSQL             │
                         └───────┬───────┬───────┬───────┬─────────────┘
                                 │       │       │       │
                     ┌───────────┘       │       │       └───────────┐
                     ▼                   ▼       ▼                   ▼
            ┌────────────────┐  ┌──────────────┐ ┌───────────────┐ ┌────────────────┐
            │ Xero Accounting │  │ Microsoft     │ │ WhatsApp       │ │ Microsoft Teams │
            │ API (OAuth2)    │  │ Graph API     │ │ Business Cloud │ │ Incoming/       │
            │                 │  │ (client creds)│ │ API (Meta)     │ │ Outgoing Webhook│
            └────────────────┘  └──────────────┘ └───────────────┘ └────────────────┘
                                                          ▲                    ▲
                                                          │                    │
                                                   Customer's phone     Technician / client
                                                   sends WhatsApp msg   posts in Teams channel

            ┌──────────────────────────────────────────────────────────────┐
            │  Managed endpoints (Windows/macOS/Linux) run monitor_agent.py  │
            │  → POST /api/endpoints/register, /api/endpoints/heartbeat     │
            └──────────────────────────────────────────────────────────────┘
```

## 2. Data model summary

- **Customer** 1—N **Contact**, **Ticket**, **Invoice**, **LicenseAssignment**, **Endpoint**
- **Ticket** 1—N **TicketComment**; tagged with a **TicketSource** enum
  (Portal, Email, WhatsApp, Teams, Phone, Endpoint Alert) so every channel
  feeds the same helpdesk queue.
- **Invoice** 1—N **InvoiceLineItem**; `xero_invoice_id` links back to the
  Xero-side record once pushed.
- **TenantLicenseSummary** (tenant-wide SKU totals) and
  **LicenseAssignment** (per-user SKU) are refreshed independently from
  Microsoft Graph's `/subscribedSkus` and `/users` endpoints.
- **Endpoint** 1—N **EndpointMetric**; `status` is derived from the most
  recent heartbeat's thresholds (disk/mem/AV/reboot) plus a "last seen"
  staleness check.
- **OAuthToken** stores refreshable tokens per integration provider
  (`xero`, and per-tenant `graph` credentials could be added the same way).

## 3. Key flows

### 3.1 WhatsApp → Ticket
1. Customer sends a WhatsApp message to the Letsma business number.
2. Meta calls `POST /webhooks/whatsapp` with the message payload.
3. `whatsapp_service.handle_inbound_payload()` matches the sender's number to
   a `Customer`/`Contact`, appends to an existing open WhatsApp ticket or
   creates a new one, and logs the raw message to `WhatsAppMessage` for audit.
4. When a technician changes the ticket status via the dashboard, a
   background task sends a WhatsApp reply to the customer automatically.

### 3.2 Teams → Ticket
1. A technician (or client, if invited to the channel) @mentions the bot:
   `@Letsma Bot New ticket: printer down at Reception for The Officers Mess`.
2. Teams calls the configured Outgoing Webhook, `POST /webhooks/teams`, with
   an HMAC signature validated against `TEAMS_OUTGOING_WEBHOOK_SECRET`.
3. `teams_service.parse_inbound_activity()` extracts the customer name after
   "for", matches it to a `Customer`, creates the ticket, and replies
   synchronously in the channel confirming the ticket number.

### 3.3 Ticket created → Teams notification (outbound)
- Any ticket creation (regardless of source) fires a background task that
  posts an Adaptive Card to the configured Incoming Webhook channel, so the
  whole team sees new tickets land in real time without checking the portal.

### 3.4 Endpoint monitoring → Alert
1. `monitor_agent.py` runs on a schedule (Task Scheduler/cron) on each
   managed device, registers once, then heartbeats every few minutes with
   CPU/RAM/disk/AV/reboot-pending data.
2. The API evaluates thresholds server-side (disk >90%, memory >95%, disk
   SMART failure, AV disabled) and flags the endpoint `Warning`.
3. If any alert condition is met, a background task posts a Teams Adaptive
   Card alert immediately - no polling required on the technician's side.
4. Endpoints that stop heartbeating are marked `Offline` automatically the
   next time the endpoints list is viewed (`AGENT_OFFLINE_THRESHOLD_MINUTES`).

### 3.5 Invoice → Xero
1. A technician creates a draft invoice against a customer (with one or more
   line items) from the Billing page, optionally ticking "push to Xero
   immediately", or pushes it later with one click.
2. `xero_service.create_invoice_in_xero()` refreshes the stored OAuth token
   if needed, maps the local `Customer`/`InvoiceLineItem` records to a Xero
   `ACCREC` invoice payload, and stores the returned `InvoiceID` /
   `InvoiceNumber` back on the local record.

### 3.6 O365 License sync
1. From a customer's detail page, a technician clicks "Sync M365 Licenses".
2. `graph_service.sync_licenses_for_customer()` obtains an app-only Graph
   token scoped to that customer's `m365_tenant_id`, pulls `/subscribedSkus`
   (tenant totals) and `/users` (per-user assigned licenses), and replaces
   the cached rows for that customer.
3. The dashboard/licenses page shows consumed vs. enabled seats per SKU, so
   under- or over-licensed tenants are visible at a glance.

## 4. Suggested production deployment (Azure)

```
Internet
   │
   ▼
Azure Front Door / App Gateway (WAF, TLS)
   │
   ▼
Azure App Service (Linux, Python) ── running this FastAPI app
   │                       │
   ▼                       ▼
Azure Database        Azure Key Vault
for PostgreSQL          (Xero/Graph/WhatsApp/Teams secrets,
(Flexible Server)        pulled at startup instead of .env)
   │
   ▼
Azure Monitor / Application Insights (logs, alerts, uptime)
```

- Use **Managed Identity** on the App Service to read Key Vault secrets
  without storing them in app settings.
- Run `monitor_agent.py` heartbeats over HTTPS only; consider issuing a
  unique API key per customer tenant rather than one shared `AGENT_API_KEY`
  once you're managing many client sites, to limit blast radius.
- For genuinely large ticket/messaging volume, move outbound WhatsApp/Teams
  notification calls from FastAPI `BackgroundTasks` to a proper queue
  (Azure Service Bus + a worker) so a slow third-party API never blocks a
  request thread.

## 5. Roadmap ideas (not built in this MVP)

- Full Bot Framework-based Teams bot (adaptive card ticket creation forms,
  proactive 1:1 reminders, buttons to change ticket status inline).
- WhatsApp template messages for structured, outside-24h-window notifications
  (e.g. invoice reminders), which Meta requires to be pre-approved templates.
- GDAP-based multi-tenant Graph access instead of one client-credentials app
  per tenant, so onboarding a new customer's M365 estate needs no per-tenant
  app registration.
- SLA breach alerting (a scheduled job comparing `sla_due_at` to now and
  escalating via Teams/email).
- Role-based access control for technicians (Admin/Manager/Technician is
  modelled on `Technician.role` already, but not yet enforced on routes).
