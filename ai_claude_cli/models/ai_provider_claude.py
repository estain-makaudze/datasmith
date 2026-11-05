"""Phase-1 stub.

The clean inheritance pattern we originally wanted (`_inherit = 'ai.provider'`
with a `_dispatch` override) is **not applicable in Odoo 19**: the native
`ai` module does not expose a `provider` ORM model. Instead, Odoo 19 routes
every LLM call through a Python utility class — `odoo.addons.ai.utils.
llm_api_service.LLMApiService` — which is hardcoded to the OpenAI and Google
code paths (see `enterprise19/ai/utils/llm_providers.py` for the PROVIDERS
list).

Routing EVERY Odoo AI feature through Claude therefore requires a monkey-patch
on `LLMApiService` to add a claude_cli branch. That is intentionally NOT shipped
in this phase-1 demo because:

    (1) monkey-patching Enterprise code across Odoo versions is brittle;
    (2) the sales value of the demo is already proven by the Settings UI
        + working subprocess test button (see res_config_settings.action_test_claude_cli);
    (3) a clean long-term fix is a separate PR *into* enterprise ai itself,
        adding a Provider("claude_cli", ...) entry and a dispatch branch.

What this phase-1 ships:
    - Third "Use your own Claude subscription" block in Settings > AI
    - A Test button that proves the subprocess routing works end-to-end
    - The subprocess wrapper (services/claude_cli.py) ready to be wired
      into any Odoo caller that wants Claude instead of OpenAI/Google.

Phase-2 roadmap (documented in README):
    - Ship a monkey-patch module that wraps LLMApiService so native
      ai.agent / ai.composer calls route through Claude.
    - Alternatively: upstream a Provider('claude_cli') PR to Odoo Enterprise.
"""
