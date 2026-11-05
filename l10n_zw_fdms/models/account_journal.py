from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    l10n_zw_device_id = fields.Many2one(
        'l10n_zw.fdms.device', string="ZIMRA Fiscal Device",
        check_company=True,
        help="Fiscalise documents of this journal on a specific device. "
             "Leave empty to use the company's registered device.",
    )
