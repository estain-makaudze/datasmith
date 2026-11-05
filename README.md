# Datasmith — Odoo 19 modules

Author: **Estain Makaudze** · estainmakaudze@gmail.com

A set of production-shaped Odoo 19 modules — two bespoke integrations (Sage 300
bridge + Claude AI backend) plus five Zimbabwe-specific business verticals I've
built. Each is independent; install only what you need.

Live multi-DB demo server (one database per module) with pre-loaded data:
**https://datasmith-demo.zimpreneur.com** · login `admin / admin`

## Modules

### Integrations (built against the Datasmith conversation)

| Module | What it does |
|---|---|
| [`sage_bridge`](./sage_bridge) | Posts Odoo customer invoices to Sage 300 as AR batches via Sage's REST Web API. Mapping tables for idempotency, queued submission with exponential-backoff retry, dead-letter handling, full audit log of every HTTP round-trip. Ships with a mock-Sage server so the demo works without a real Sage install. |
| [`ai_claude_cli`](./ai_claude_cli) | Adds a third provider to Odoo 19 Enterprise's native AI (Settings → AI → Providers): "Use your own Claude subscription". Monkey-patches `LLMApiService._request_llm` to route every Odoo AI call through the local `claude` CLI with scoped `Bash(psql *)` tool access. Zero per-call API cost, data never leaves the server. |
| [`mock_sage_server`](./mock_sage_server) | A Flask app mirroring Sage 300's REST Web API contract. Not an Odoo module — a standalone companion for `sage_bridge`. Reusable for any Sage integration dev work where a real Sage licence isn't at hand. |

### Zimbabwe vertical modules

| Module | Vertical |
|---|---|
| [`fuel_module`](./fuel_module) | Fuel stations — sites, pumps, nozzles, tanks, attendants, shifts, cash-ups. |
| [`freight_module`](./freight_module) | Freight / clearing agents — consignments, ports, HS tariff codes, disbursement categories. |
| [`transport_module`](./transport_module) | Passenger transport (kombi/bus) — fleet, drivers, routes, daily cash-ups, driver payment schemes. |
| [`l10n_zw`](./l10n_zw) | Zim accounting base — chart of accounts + ZIMRA VAT rates (15.5% / 0% / exempt / 5% WHT). |
| [`l10n_zw_fdms`](./l10n_zw_fdms) | ZIMRA FDMS fiscalisation — SHA-256 + ECDSA-P256 receipt signing with hash chaining, async submission queue, QR + verification code, fiscal day lifecycle. Depends on `l10n_zw`. |

## For the code reviewer — recommended reading order

1. **`sage_bridge/README.md`** → `sage_bridge/services/sage_api.py` → `sage_bridge/models/sage_sync_job.py` — the integration client + queue + retry.
2. **`ai_claude_cli/README.md`** → `ai_claude_cli/models/ai_provider_claude.py` → `ai_claude_cli/services/claude_cli.py` — the monkey-patch hook + subprocess wrapper.
3. **`mock_sage_server/README.md`** → `mock_sage_server/app.py` — the pseudo-Sage REST endpoints.

Each module's own README opens with a "for the reviewer, start here" block pointing to the 3–5 key files. About 15 minutes per module to orient.

## Live demo — what to click

`datasmith_sage`
- Open any customer invoice, post it, then open the **Sage 300 → Sync Queue** menu.
- Two invoices are already pushed to the mock Sage server with full HTTP logs.

`datasmith_ai`
- Click the **"Ask AI"** icon top-right.
- Ask *"list my customers"* or *"how many invoices do I have?"* — Claude runs a scoped psql query and replies.

`datasmith_fuel` / `datasmith_freight` / `datasmith_transport` / `datasmith_pos`
- Open the main menu of each and click through the forms.
- Transport comes pre-loaded with 5 vehicles + 8 drivers.
- POS has a Demo-mode FDMS virtual device registered.

## Install (standalone)

```bash
cd /path/to/odoo/custom-addons
git clone https://github.com/estain-makaudze/datasmith.git
./odoo-bin -d <db> -i sage_bridge        # or ai_claude_cli, fuel_module, etc.
```

Each module's `__manifest__.py` declares its own dependencies. The AI module requires Odoo 19 Enterprise (inherits the Enterprise `ai` module); everything else works on Community.

## License

LGPL-3. See [`LICENSE`](./LICENSE).
