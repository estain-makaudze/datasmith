from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    l10n_zw_fdms_device_ids = fields.One2many('l10n_zw.fdms.device', 'company_id')

    def _l10n_zw_fdms_enabled(self):
        """Fiscalisation applies when the company has a registered device."""
        self.ensure_one()
        return bool(self.l10n_zw_fdms_device_ids.filtered(
            lambda d: d.state == 'registered' and d.active))
