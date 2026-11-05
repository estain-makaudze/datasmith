# Sage 300 Bridge — Odoo 19

Author: **Estain Makaudze** · estainmakaudze@gmail.com

Pushes Odoo customer invoices to Sage 300 as AR batches via Sage's REST Web API.
Production-shaped: mapping tables for idempotency, queued async submission,
exponential-backoff retry, dead-letter handling, full HTTP audit log.

Runs end-to-end out of the box against the mock-Sage server shipped alongside
this module (`../mock_sage_server`). Flip `demo_mode` off and swap the base URL
to go live against a real Sage 300 install — zero code changes.

## For the code reviewer — start here

1. **`services/sage_api.py`** — the REST client. Thin HTTP wrapper with Basic Auth,
   logs every round-trip into `sage.sync.log`, raises `SageApiError` on anything
   non-2xx or network. `push_invoice()` is the main entry point.
2. **`models/sage_sync_job.py`** — the queue. `enqueue()` is idempotent (same
   (config, move) → same job). `_cron_drain()` is the worker. `_mark_failed()`
   does the exponential-backoff logic and dead-letter transition.
3. **`models/account_move.py`** — the Odoo hook. Overrides `_post` so posting an
   invoice auto-enqueues; also exposes an "Push to Sage 300" button for manual.
4. **`models/sage_invoice_mapping.py`** + **`models/sage_customer_mapping.py`** —
   the idempotency keys. Why pushing the same invoice twice never creates two
   Sage documents.
5. **`tests/test_sage_push.py`** — the full flow verified end-to-end: enqueue,
   drain, map, retry, dead-letter. Mocks `SageApi` so tests don't need the server.

## Architecture

```
account.move  (invoice posted)
        │
        │ _post override
        ▼
sage.sync.job  (status=pending)
        │
        │ ir.cron every 2min OR immediate on manual button
        ▼
SageApi.push_invoice()
        │   logs every HTTP call → sage.sync.log
        ▼
┌────────────────────────┐
│  real Sage 300 server  │   OR    ┌──────────────────────┐
│  (production)          │         │  mock_sage_server    │
└────────────────────────┘         │  (demo_mode=True)    │
                                   └──────────────────────┘
        │
        ▼
sage.invoice.mapping  (batch_no + doc_no stored, idempotency secured)
```

**Trading never blocks on Sage.** Posting in Odoo is synchronous and local;
the HTTP call happens asynchronously via the cron. If Sage is unreachable,
jobs queue up; when Sage returns, the queue drains. Failures retry at
1min / 5min / 25min, then move to dead-letter for human review.

## Install

```bash
cd /path/to/odoo/addons
ln -s /path/to/zimpreneur-datasmith/sage_bridge .
./odoo-bin -d <db> -i sage_bridge
```

On install, a demo `sage.config` is created pointing at
`https://mock-sage.datasmith-demo.zimpreneur.com`. Install with `--demo`
to also get a demo customer (Acme Corporation).

## Running the demo

1. Sage 300 → Configuration → Connections → **Demo Sage 300 (mock server)**
2. Click **Test Connection** → should go green
3. Accounting → Customers → Acme Corporation → New Invoice
4. Post the invoice. A sync job appears in **Sage 300 → Sync Queue**.
5. Either wait up to 2min for the cron to run, or click **Push to Sage 300**
   on the invoice to run immediately.
6. Invoice now shows **Sage Document Number** and **Sage Batch Number**.
7. **Sage 300 → HTTP Log** shows every API call made, request + response bodies.

Verify from the outside:

```bash
curl -u demo:demo123 https://mock-sage.datasmith-demo.zimpreneur.com/v1.0/-/DEMO01/AR/Customers
curl -u demo:demo123 https://mock-sage.datasmith-demo.zimpreneur.com/v1.0/-/DEMO01/AR/InvoiceBatches
```

The invoice you just posted is there.

## Going live against a real Sage 300

In the `sage.config`:

1. `base_url` → the real Sage 300 Web API, e.g. `https://sage.example.com/Sage300WebApi`
2. `company_code` → the real company database code (e.g. `SAMINC`)
3. `username` / `password` → a **dedicated service user** on Sage (never a human login)
4. `demo_mode` → OFF (cosmetic only — just removes the demo ribbon)
5. Click **Test Connection**

No code changes. Same client, same client, real server.

## Tests

```bash
./odoo-bin -d <db> -i sage_bridge --test-enable --test-tags sage_bridge --stop-after-init
```

Covers: idempotent enqueue, mapping on success, retry-with-backoff on failure,
dead-letter after max retries.

## What this module intentionally does NOT do (yet)

Deferred to Phase 2:

- Vendor bills / AP push (same pattern, trivial to add)
- Payment sync back (Sage receipts → Odoo payment reconciliation)
- Multi-currency conversion (uses the invoice's own currency; Sage must accept it)
- OData `$filter` queries for reporting (we only write, don't query back)
- Multi-entity Sage servers (one company per config; multiple configs if needed)

Each is a one-line conversation when a client asks. The architecture already
supports them — they just aren't written for this demo.

## License

LGPL-3. See `../LICENSE`.
