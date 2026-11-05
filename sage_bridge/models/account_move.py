import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    """Hook into customer invoice posting: on post, enqueue a Sage push job."""

    _inherit = "account.move"

    sage_mapping_id = fields.Many2one(
        "sage.invoice.mapping",
        compute="_compute_sage_mapping",
        help="The Sage mapping record for this invoice, if one exists.",
    )
    sage_document_number = fields.Char(related="sage_mapping_id.sage_document_number", store=False)
    sage_batch_number = fields.Char(related="sage_mapping_id.sage_batch_number", store=False)
    sage_posted = fields.Boolean(related="sage_mapping_id.sage_posted", store=False)

    def _compute_sage_mapping(self):
        Mapping = self.env["sage.invoice.mapping"]
        for move in self:
            move.sage_mapping_id = Mapping.search([("move_id", "=", move.id)], limit=1)

    def _post(self, soft=True):
        """Override: after the standard post succeeds, enqueue push if config says so."""
        posted = super()._post(soft=soft)
        # Only for customer invoices + credit notes; skip vendor bills + anything in draft
        pushable = posted.filtered(
            lambda m: m.move_type in ("out_invoice", "out_refund") and m.state == "posted"
        )
        for move in pushable:
            config = self.env["sage.config"]._get_default_config()
            if config and config.auto_push_on_post:
                try:
                    self.env["sage.sync.job"].enqueue(move, config=config)
                except Exception as e:   # noqa: BLE001 — don't block posting on sage
                    _logger.warning("sage_bridge: failed to enqueue %s: %s", move.name, e)
                    move.message_post(
                        body=_("Sage 300 push could not be queued: %s") % e,
                        subtype_xmlid="mail.mt_note",
                    )
        return posted

    def action_push_to_sage(self):
        """Manual push button on the invoice form."""
        self.ensure_one()
        if self.state != "posted":
            raise UserError(_("Only posted invoices can be pushed to Sage 300."))
        if self.move_type not in ("out_invoice", "out_refund"):
            raise UserError(_("Only customer invoices and credit notes are pushed to Sage 300."))
        config = self.env["sage.config"]._get_default_config()
        if not config:
            raise UserError(_("Configure a Sage 300 connection first."))
        job = self.env["sage.sync.job"].enqueue(self, config=config)
        # Run immediately (bypass the cron for the manual action — nicer UX)
        job._run()
        if job.status == "done":
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Pushed to Sage 300"),
                    "message": _("Batch %s · Document %s") % (
                        job.move_id.sage_batch_number or "—",
                        job.move_id.sage_document_number or "—",
                    ),
                    "type": "success",
                },
            }
        raise UserError(_("Push failed: %s") % (job.last_error or "unknown error"))
