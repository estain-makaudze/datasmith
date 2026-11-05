from odoo import api, fields, models


class SageCustomerMapping(models.Model):
    """Idempotency table: one Odoo partner <-> one Sage customer number, per Sage config.

    Why: before pushing an invoice we need the Sage CustomerNumber. First push
    creates it in Sage and records the mapping here; every subsequent push looks
    it up instead of re-creating.
    """

    _name = "sage.customer.mapping"
    _description = "Sage ↔ Odoo Customer Mapping"
    _rec_name = "sage_customer_number"
    _order = "synced_at desc"

    config_id = fields.Many2one("sage.config", required=True, ondelete="cascade")
    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade")
    sage_customer_number = fields.Char(required=True, index=True)
    synced_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    last_pushed_payload = fields.Text(readonly=True, help="Last JSON sent to Sage for audit.")

    _sql_constraints = [
        (
            "partner_per_config_uniq",
            "unique(config_id, partner_id)",
            "A partner can only map to one Sage customer per Sage config.",
        ),
    ]
