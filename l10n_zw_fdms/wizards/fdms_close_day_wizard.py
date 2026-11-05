from odoo import _, api, fields, models
from odoo.exceptions import UserError


class L10nZwFdmsCloseDayWizard(models.TransientModel):
    _name = 'l10n_zw.fdms.close.day.wizard'
    _description = 'Close ZIMRA Fiscal Day'

    device_id = fields.Many2one('l10n_zw.fdms.device', required=True)
    fiscal_day_id = fields.Many2one(
        'l10n_zw.fiscal.day', compute='_compute_fiscal_day', store=True, readonly=False)
    document_count = fields.Integer(compute='_compute_summary')
    unsent_count = fields.Integer(compute='_compute_summary')
    counters_preview = fields.Text(compute='_compute_summary')
    force = fields.Boolean(
        string="Close even with unsubmitted documents",
        help="Unsent receipts will keep retrying but the day close may fail "
             "server-side until they are submitted.",
    )

    @api.depends('device_id')
    def _compute_fiscal_day(self):
        for wizard in self:
            wizard.fiscal_day_id = wizard.device_id.current_fiscal_day_id

    @api.depends('fiscal_day_id')
    def _compute_summary(self):
        for wizard in self:
            day = wizard.fiscal_day_id
            docs = day.document_ids if day else self.env['l10n_zw.fdms.document']
            wizard.document_count = len(docs)
            wizard.unsent_count = len(docs.filtered(lambda d: d.state != 'sent'))
            if day:
                counters = day._compute_fiscal_day_counters()
                wizard.counters_preview = '\n'.join(
                    f"{c['fiscalCounterType']} {c['fiscalCounterCurrency']}"
                    f"{' ' + str(c.get('fiscalCounterMoneyType')) if c.get('fiscalCounterMoneyType') else ''}"
                    f"{' ' + str(c.get('fiscalCounterTaxPercent')) + '%' if c.get('fiscalCounterTaxPercent') is not None else ''}"
                    f": {c['fiscalCounterValue']:.2f}"
                    for c in counters
                ) or _("No activity this fiscal day.")
            else:
                wizard.counters_preview = False

    def action_close(self):
        self.ensure_one()
        if not self.fiscal_day_id:
            raise UserError(_("No open fiscal day on device %s.", self.device_id.name))
        if not self.fiscal_day_id.action_close(force=self.force):
            raise UserError(_(
                "The CloseDay call failed: %s",
                self.fiscal_day_id.close_error or _("see the fiscal day record.")))
        return {'type': 'ir.actions.act_window_close'}
