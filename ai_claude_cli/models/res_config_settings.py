import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    """Add the 'Use your own Claude subscription' block to Settings → AI → Providers."""

    _inherit = "res.config.settings"

    use_claude_cli = fields.Boolean(
        string="Use your own Claude subscription",
        config_parameter="ai_claude_cli.enabled",
        help="Route all Odoo AI features through the local `claude` CLI "
             "(your Claude Code / Claude Max subscription) instead of an API key.",
    )
    claude_cli_path = fields.Char(
        string="Path to claude binary",
        config_parameter="ai_claude_cli.binary_path",
        default="/usr/local/bin/claude",
        help="Absolute path to the `claude` executable. On the demo server this "
             "is typically /usr/local/bin/claude. Leave default if `claude` is on the Odoo user's PATH.",
    )
    claude_cli_model = fields.Char(
        string="Claude model",
        config_parameter="ai_claude_cli.model",
        default="sonnet",
        help="Model identifier passed to the Claude CLI (--model). "
             "Common values: sonnet, opus, haiku. Default: sonnet.",
    )
    claude_cli_timeout = fields.Integer(
        string="Request timeout (seconds)",
        config_parameter="ai_claude_cli.timeout",
        default=60,
        help="Kill the subprocess if Claude doesn't respond within this many seconds.",
    )

    def action_test_claude_cli(self):
        """Test the CLI end-to-end: send an actual prompt, confirm subscription works."""
        self.ensure_one()
        from ..services.claude_cli import ClaudeCliBackend, ClaudeCliError
        backend = ClaudeCliBackend(self.env)
        try:
            text = backend.call(prompt="Reply with exactly: OK", system_prompt=None, timeout=15)
            ok = "OK" in (text or "").upper()
            if ok:
                return self._notify(
                    _("Claude CLI connected"),
                    _("Claude responded: %s") % text.strip()[:120],
                    "success",
                )
            return self._notify(
                _("Claude CLI responded but not as expected"),
                _("Response was: %s") % text.strip()[:200],
                "warning",
            )
        except ClaudeCliError as e:
            return self._notify(_("Claude CLI test failed"), str(e), "danger", sticky=True)

    @staticmethod
    def _notify(title, message, kind, sticky=False):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": title,
                "message": message,
                "type": kind,
                "sticky": sticky,
            },
        }
