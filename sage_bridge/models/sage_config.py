import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class SageConfig(models.Model):
    """One Sage 300 server/company we push to. A company can have several."""

    _name = "sage.config"
    _description = "Sage 300 Connection"
    _order = "sequence, id"

    name = fields.Char(required=True, help="Label shown in the UI, e.g. 'Sage 300 Live' or 'Sage 300 Test'.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    base_url = fields.Char(
        string="Web API Base URL",
        required=True,
        default="https://mock-sage.datasmith-demo.zimpreneur.com",
        help="Base URL of the Sage 300 Web API, including scheme. "
             "Example: https://sage.example.com/Sage300WebApi",
    )
    company_code = fields.Char(
        string="Sage Company Code",
        required=True,
        default="DEMO01",
        help="The 2-6 char Sage 300 company database code, e.g. 'SAMINC', 'DEMO01'.",
    )
    username = fields.Char(required=True, default="demo")
    password = fields.Char(required=True, default="demo123")

    demo_mode = fields.Boolean(
        default=True,
        help="When ticked, the base_url is treated as a mock-Sage server (ships with "
             "this repo). Turn OFF in production and point base_url at the real "
             "Sage 300 Web API.",
    )

    # Behaviour toggles
    auto_push_on_post = fields.Boolean(
        string="Auto-push on invoice post",
        default=True,
        help="When a customer invoice is posted in Odoo, queue it for Sage automatically.",
    )
    max_retries = fields.Integer(
        default=3,
        help="Number of attempts before a sync job is moved to dead-letter.",
    )
    retry_backoff_seconds = fields.Integer(
        default=60,
        help="Base delay before the first retry; subsequent retries multiply by 5.",
    )

    # Audit fields
    last_tested_at = fields.Datetime(readonly=True)
    last_tested_ok = fields.Boolean(readonly=True)
    last_tested_message = fields.Char(readonly=True)

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Sage connection name must be unique."),
    ]

    def action_test_connection(self):
        """Hit a cheap read endpoint to verify auth + reachability."""
        self.ensure_one()
        from ..services.sage_api import SageApi
        client = SageApi(self)
        ok, message = client.test_connection()
        self.write({
            "last_tested_at": fields.Datetime.now(),
            "last_tested_ok": ok,
            "last_tested_message": message,
        })
        kind = "success" if ok else "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Sage 300 connection"),
                "message": message,
                "type": kind,
                "sticky": not ok,
            },
        }

    @api.constrains("base_url")
    def _check_base_url(self):
        for rec in self:
            url = (rec.base_url or "").strip()
            if not (url.startswith("http://") or url.startswith("https://")):
                raise ValidationError(_("Web API Base URL must start with http:// or https://"))

    @api.model
    def _get_default_config(self):
        """Pick the first active config. Most SMEs only have one."""
        return self.search([("active", "=", True)], limit=1)
