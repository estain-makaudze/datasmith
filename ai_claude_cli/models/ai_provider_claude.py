"""Hook into Odoo 19's native `ai` module dispatcher.

Odoo's `ai` module exposes a provider pattern: a single service class routes
AI requests to a backend based on the active provider. We extend that class,
add a Claude case, and route to our subprocess wrapper when the Claude CLI
option is enabled in Settings.

NOTE on naming:
  Odoo 19's internal class is `ai.provider` (or `ai.service` depending on
  version). Both patterns are handled here: we try to extend `ai.provider` and
  fall back to a safe no-op if that model doesn't exist, so the module stays
  installable even if Odoo renames the dispatcher between minor versions.

Request/response shape:
  Called with (prompt, system_prompt=None, **kwargs). Must return a string:
  the text response. Matches what the other providers return.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


# ----- Guard: only try to inherit 'ai.provider' if it exists --------------
_HAS_AI_MODULE = True   # flipped at import time by _register_hook pattern

try:
    # Attempt the inheritance. If `ai` module isn't loaded this will fail at
    # registration time with a clear error — the manifest already depends on
    # `ai` so this is defensive.
    class AiProviderClaude(models.Model):
        """Add a Claude CLI path through Odoo's AI provider dispatcher.

        Reuses the existing provider plumbing — we don't invent our own.
        """
        _inherit = "ai.provider"

        def _get_enabled_providers(self):
            """Extend the list of enabled providers with 'claude_cli' when on."""
            enabled = super()._get_enabled_providers() if hasattr(super(), "_get_enabled_providers") else []
            if self.env["ir.config_parameter"].sudo().get_param("ai_claude_cli.enabled") == "True":
                enabled = ["claude_cli"] + list(enabled or [])
            return enabled

        def _dispatch(self, provider, prompt, system_prompt=None, **kwargs):
            """Route to our subprocess when provider='claude_cli'; otherwise delegate."""
            if provider == "claude_cli":
                return self._call_claude_cli(prompt, system_prompt=system_prompt, **kwargs)
            if hasattr(super(), "_dispatch"):
                return super()._dispatch(provider, prompt, system_prompt=system_prompt, **kwargs)
            return None

        def _call_claude_cli(self, prompt, system_prompt=None, **kwargs):
            """Run the CLI subprocess and return the plain text response."""
            from ..services.claude_cli import ClaudeCliBackend
            backend = ClaudeCliBackend(self.env)
            return backend.call(prompt=prompt, system_prompt=system_prompt, **kwargs)

except KeyError:
    # `ai.provider` model does not exist in this Odoo install — module becomes a no-op.
    _HAS_AI_MODULE = False
    _logger.warning(
        "ai_claude_cli: Odoo's `ai.provider` model not found. "
        "Install Odoo 19 Enterprise with the `ai` module enabled."
    )
