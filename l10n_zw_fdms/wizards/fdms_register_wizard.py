from odoo import _, fields, models
from odoo.exceptions import UserError


class L10nZwFdmsRegisterWizard(models.TransientModel):
    _name = 'l10n_zw.fdms.register.wizard'
    _description = 'Register ZIMRA Fiscal Device'

    device_id = fields.Many2one('l10n_zw.fdms.device', required=True)
    state = fields.Selection(
        [('verify', 'Verify'), ('confirm', 'Confirm')],
        default='verify', required=True,
    )
    taxpayer_name = fields.Char(readonly=True)
    taxpayer_tin = fields.Char(readonly=True)
    taxpayer_vat_number = fields.Char(readonly=True)
    branch_name = fields.Char(readonly=True)

    def action_verify(self):
        """Step 1: VerifyTaxpayerInformation — show who ZIMRA thinks we are."""
        self.ensure_one()
        device = self.device_id
        if device.mode != 'demo' and not device.activation_key:
            raise UserError(_("Set the activation key on the device first."))
        error, data = self.env['l10n_zw.fdms.api']._call_fdms(
            device, 'POST', 'VerifyTaxpayerInformation',
            payload={
                'activationKey': device.activation_key,
                'deviceSerialNo': device.serial_number,
            },
            public=True,
        )
        if error:
            raise UserError(_("Taxpayer verification failed: %s", error.get('message', error)))
        self.write({
            'state': 'confirm',
            'taxpayer_name': data.get('taxPayerName'),
            'taxpayer_tin': data.get('taxPayerTIN'),
            'taxpayer_vat_number': data.get('vatNumber'),
            'branch_name': data.get('deviceBranchName'),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_register(self):
        """Step 2: generate key + CSR, register, fetch config."""
        self.ensure_one()
        device = self.device_id
        device.write({
            'taxpayer_name': self.taxpayer_name,
            'taxpayer_tin': self.taxpayer_tin,
            'taxpayer_vat_number': self.taxpayer_vat_number,
            'branch_name': self.branch_name,
        })
        self.env['l10n_zw.fdms.api']._register_device(device)
        return {'type': 'ir.actions.act_window_close'}
