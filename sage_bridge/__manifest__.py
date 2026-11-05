{
    "name": "Sage 300 Bridge",
    "version": "19.0.1.0.0",
    "category": "Accounting/Integrations",
    "summary": "Push Odoo customer invoices to Sage 300 as AR batches via the REST Web API",
    "description": """
Sage 300 Bridge
===============

Integration layer that posts customer invoices from Odoo to Sage 300 as AR batches
using Sage's REST Web API (/Sage300WebApi/v1.0/-/{company}/AR/...).

Shipped with:
  * Mapping tables for idempotency (one Sage batch per Odoo invoice, forever)
  * Queued submission with exponential-backoff retry (1m, 5m, 25m) + dead-letter
  * Full audit log of every HTTP round-trip (request, response, status, duration)
  * Dashboard view of sync status and failures
  * Demo-mode toggle that points the client at an included mock-Sage server
    (see ../mock_sage_server) so the full flow works without a real Sage install

The REST client is written against Sage's documented Web API contract — no SDK,
no COM, no Windows-only dependency. Runs anywhere Odoo runs.
    """,
    "author": "Estain Makaudze",
    "website": "https://github.com/estain-makaudze/zimpreneur-datasmith",
    "license": "LGPL-3",
    "depends": [
        "account",
        "mail",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/sage_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "data/demo_config.xml",
        "views/sage_config_views.xml",
        "views/sage_sync_job_views.xml",
        "views/sage_sync_log_views.xml",
        "views/account_move_views.xml",
        "views/menus.xml",
    ],
    "demo": [
        "data/demo_customer.xml",
    ],
    "installable": True,
    "application": True,
}
