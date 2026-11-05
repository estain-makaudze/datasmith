from odoo import fields, models


class SageInvoiceMapping(models.Model):
    """Idempotency table: one Odoo account.move <-> one Sage AR batch/document.

    After a successful push we store the Sage batch + document numbers here,
    so retries never duplicate and users can click back from the Odoo invoice
    into the Sage record.
    """

    _name = "sage.invoice.mapping"
    _description = "Sage ↔ Odoo Invoice Mapping"
    _rec_name = "sage_document_number"
    _order = "synced_at desc"

    config_id = fields.Many2one("sage.config", required=True, ondelete="cascade")
    move_id = fields.Many2one("account.move", required=True, ondelete="cascade")
    sage_batch_number = fields.Char(index=True)
    sage_document_number = fields.Char(index=True)
    sage_posted = fields.Boolean(default=False, help="True once Sage batch is posted to the GL.")
    synced_at = fields.Datetime(default=fields.Datetime.now, readonly=True)

    _sql_constraints = [
        (
            "move_per_config_uniq",
            "unique(config_id, move_id)",
            "An invoice can only map to one Sage document per Sage config.",
        ),
    ]
