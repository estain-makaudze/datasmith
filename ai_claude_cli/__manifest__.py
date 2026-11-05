{
    "name": "AI: Claude CLI Backend",
    "version": "19.0.1.0.0",
    "category": "AI",
    "summary": "Adds a third provider to Odoo AI Settings — use your own Claude subscription via the local `claude` CLI instead of an API key",
    "description": """
AI: Claude CLI Backend
======================

Adds "Use your own Claude subscription" as a third provider in
**Settings → AI → Providers**, next to OpenAI and Gemini. Instead of an API key
field, the provider calls the local `claude` CLI binary as a subprocess —
routing every Odoo AI feature (Ask AI drawer, Agents, Pivot/chart suggestions,
the full Enterprise AI surface) through the user's Claude Code / Claude Max
subscription.

Zero new UI. Zero new models. Pure inheritance on Odoo's `ai.provider`
dispatcher — one case added, same request/response shape as OpenAI and Gemini.

Why
---
OpenAI + Gemini API keys cost per call. A Claude Code subscription is flat
monthly, unlimited at its tier. For an SME office with 20 users each asking
AI 10x a day, that's ~$30–150/month saved vs OpenAI, plus data stays on-prem.

Prerequisite
------------
The `claude` CLI must be installed on the Odoo server and readable by the Odoo
system user. One-time setup on the server:
    sudo -u odoo claude /login
    sudo -u odoo claude -p "say OK"   # confirm it works

Then in Odoo: Settings → AI → tick 'Use your own Claude subscription' → save.
    """,
    "author": "Estain Makaudze",
    "website": "https://github.com/estain-makaudze/zimpreneur-datasmith",
    "license": "LGPL-3",
    "depends": [
        "ai",   # Odoo 19 Enterprise AI module
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
    ],
    "installable": True,
    "application": False,
}
