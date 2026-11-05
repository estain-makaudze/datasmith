from odoo import fields, models


class AccountTax(models.Model):
    _inherit = 'account.tax'

    # ZIMRA FDMS tax identifiers. The taxID is assigned by ZIMRA and returned
    # by the device GetConfig call (applicableTaxes). Known values at the time
    # of writing: 2 = zero rated 0%, 3 = exempt, 514 = 5% non-VAT withholding,
    # 515 = standard VAT 15.5%.
    l10n_zw_tax_id = fields.Integer(
        string="ZIMRA Tax ID",
        help="Tax identifier assigned by ZIMRA FDMS (see the device configuration's "
             "applicable taxes). Required on every tax used on fiscalised documents.",
    )
    l10n_zw_tax_code = fields.Char(
        string="ZIMRA Tax Code",
        size=3,
        help="Optional ZIMRA tax code letter (as shown on fiscal receipts).",
    )
    l10n_zw_is_exempt = fields.Boolean(
        string="ZIMRA Exempt Tax",
        help="Exempt taxes are reported to ZIMRA without a tax percentage "
             "(this is different from a 0% rate).",
    )

    def _l10n_zw_signature_percent(self):
        """Return the taxPercent component used in FDMS signature strings.

        Exempt taxes contribute an empty string; every other tax contributes
        its percentage formatted with two decimals (e.g. '15.50', '0.00').
        """
        self.ensure_one()
        if self.l10n_zw_is_exempt:
            return ''
        return f'{self.amount:.2f}'
