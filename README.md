# Zimpreneur × Datasmith

Author: **Estain Makaudze** · estainmakaudze@gmail.com

A focused pair of Odoo 19 integration modules built to show the depth of integration
work I can take on as a subcontract engineer — a Sage 300 bridge and a Claude CLI
backend for Odoo's native AI module. Each is production-shaped (config, mapping,
service, hook, queue, retry, audit log, tests), demo-ready, and self-contained
enough to read top-to-bottom in 20 minutes.

Live multi-DB demo server (one DB per module): **https://datasmith-demo.zimpreneur.com**

## Modules in this repo

### 1. `sage_bridge` — Odoo 19 → Sage 300 integration

Posts customer invoices from Odoo to Sage 300 as AR batches via Sage's REST Web API.
Mapping tables for idempotency, queued submission with exponential-backoff retry,
dead-letter handling, full audit log of every HTTP round-trip.

**Ships with an external mock-Sage server** (`mock_sage_server/`) that mirrors the
Sage 300 Web API contract exactly. Means the full flow works end-to-end without
needing a real Sage install — real HTTPS calls, real OData responses, real auth,
all visible in `curl`, Postman, or browser dev tools.

### 2. `ai_claude_cli` — Claude backend for Odoo's native AI

Adds a third provider to **Settings → AI → Providers** ("Use your own Claude
subscription"). Routes every Odoo AI feature — Ask AI, Agents, Pivot/chart
suggestions, the full Enterprise AI surface — through the local `claude` CLI
instead of an API key.

Zero new UI. Zero new models. Pure inheritance on Odoo's `ai.provider` dispatcher.
Odoo 19 Enterprise required (the `ai` module being extended is Enterprise-only).

### 3. `mock_sage_server` — companion Flask service

Not an Odoo module. A small Flask app that mimics Sage 300's Web API on these
endpoints:

- `GET  /v1.0/-/{company}/AR/Customers`
- `POST /v1.0/-/{company}/AR/InvoiceBatches`
- `POST /v1.0/-/{company}/AR/InvoiceEntries`
- `POST /v1.0/-/{company}/AR/InvoiceBatches/{id}/Post`
- `GET  /v1.0/-/{company}/AR/InvoiceBatches/{id}`

Authentication via HTTP Basic Auth (demo/demo123). SQLite backing store so pushed
invoices persist and are queryable. Run standalone or deployed next to the demo
Odoo instance.

## Why "Zimpreneur × Datasmith"

Zimpreneur is my Zimbabwe-vertical Odoo product line; Datasmith is the context
this pair was prepared for. The naming makes the intent explicit: these modules
were built against the integration patterns Datasmith's Odoo partner work actually
uses.

## For the code reviewer — recommended reading order

1. **`sage_bridge/README.md`** → `sage_bridge/services/sage_api.py` → `sage_bridge/models/sage_sync_job.py` — the integration client + queue
2. **`ai_claude_cli/README.md`** → `ai_claude_cli/models/ai_provider_claude.py` → `ai_claude_cli/services/claude_cli.py` — the provider hook + subprocess wrapper
3. **`mock_sage_server/README.md`** → `mock_sage_server/app.py` — the pseudo-Sage REST endpoints

All three have a "for the reviewer, start here" section at the top of their own README.

## Live demo

Multi-database Odoo 19 Enterprise at **https://datasmith-demo.zimpreneur.com**:

- `datasmith_sage` — Odoo with `sage_bridge` installed, sample customer + invoice pre-loaded
- `datasmith_ai` — Odoo with `ai_claude_cli` installed and Claude provider pre-selected
- Login for both: `brandon@datasmith.co.za` / `datasmith2026`

Mock-Sage endpoint for `sage_bridge`: **https://mock-sage.datasmith-demo.zimpreneur.com**
(`curl -u demo:demo123 .../v1.0/-/DEMO01/AR/Customers`)

## License

LGPL-3. See `LICENSE`.
