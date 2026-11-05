import logging

from psycopg2 import OperationalError
from psycopg2.errorcodes import LOCK_NOT_AVAILABLE

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class L10nZwFdmsDevice(models.Model):
    _name = 'l10n_zw.fdms.device'
    _description = 'ZIMRA Fiscal Device'
    _check_company_auto = True

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)
    device_id = fields.Integer(string="Device ID", required=True)
    serial_number = fields.Char(string="Device Serial No", required=True)
    activation_key = fields.Char(
        help="8-character activation key issued by ZIMRA. Only needed until the "
             "device is registered.",
    )
    model_name = fields.Char(
        string="Device Model Name", required=True, default='Server',
        help="Sent as the DeviceModelName header; must match the model name "
             "registered with ZIMRA.",
    )
    model_version = fields.Char(
        string="Device Model Version", required=True, default='v1',
        help="Sent as the DeviceModelVersion header.",
    )
    mode = fields.Selection(
        [
            ('demo', 'Demo (offline mock)'),
            ('test', 'ZIMRA Test'),
            ('prod', 'ZIMRA Production'),
        ],
        required=True, default='demo',
    )
    state = fields.Selection(
        [
            ('draft', 'Not Registered'),
            ('registered', 'Registered'),
            ('blocked', 'Blocked'),
        ],
        default='draft', required=True, copy=False,
    )
    key_id = fields.Many2one('certificate.key', string="Device Private Key", copy=False)
    certificate_id = fields.Many2one('certificate.certificate', string="Device Certificate", copy=False)

    # --- GetConfig / VerifyTaxpayerInformation cache ---
    config_json = fields.Json(copy=False)
    applicable_taxes = fields.Json(
        copy=False,
        help="applicableTaxes from GetConfig: list of {taxID, taxName, taxPercent, "
             "validFrom, validTill}.",
    )
    qr_url = fields.Char(copy=False, default='https://fdmstest.zimra.co.zw/')
    tax_payer_day_max_hrs = fields.Integer(default=24, copy=False)
    certificate_valid_till = fields.Datetime(copy=False)
    operating_mode = fields.Char(copy=False)
    taxpayer_name = fields.Char(copy=False)
    taxpayer_tin = fields.Char(copy=False)
    taxpayer_vat_number = fields.Char(copy=False)
    branch_name = fields.Char(copy=False)
    branch_address = fields.Char(copy=False)

    # --- gap-free counter state; mutated only while holding _lock() ---
    receipt_global_no = fields.Integer(
        default=0, copy=False,
        help="Last used receiptGlobalNo (device lifetime, never resets).",
    )
    last_receipt_hash = fields.Char(
        copy=False,
        help="Base64 SHA-256 hash of the last signed receipt of the current "
             "fiscal day (the chain restarts each fiscal day).",
    )
    current_fiscal_day_id = fields.Many2one('l10n_zw.fiscal.day', copy=False)

    document_count = fields.Integer(compute='_compute_counts')
    fiscal_day_count = fields.Integer(compute='_compute_counts')

    _device_company_uniq = models.Constraint(
        'unique(company_id, device_id)',
        "This ZIMRA device ID already exists for this company.")

    def _compute_counts(self):
        doc_counts = dict(self.env['l10n_zw.fdms.document']._read_group(
            [('device_id', 'in', self.ids)], ['device_id'], ['__count']))
        day_counts = dict(self.env['l10n_zw.fiscal.day']._read_group(
            [('device_id', 'in', self.ids)], ['device_id'], ['__count']))
        for device in self:
            device.document_count = doc_counts.get(device, 0)
            device.fiscal_day_count = day_counts.get(device, 0)

    # ------------------------------------------------------------------
    # Locking & counter allocation
    # ------------------------------------------------------------------

    def _lock(self, nowait=True):
        """Take a row lock on the device, serialising all chain mutations.

        The fiscal chain (receiptGlobalNo, per-day counter, previous hash)
        must advance without gaps or races; every signing transaction must
        hold this lock until commit.
        """
        self.ensure_one()
        try:
            self.env.cr.execute(
                f"SELECT id FROM l10n_zw_fdms_device WHERE id = %s FOR UPDATE{' NOWAIT' if nowait else ''}",
                [self.id],
            )
        except OperationalError as e:
            if e.pgcode == LOCK_NOT_AVAILABLE:
                raise UserError(_(
                    "Another transaction is currently fiscalising a document on "
                    "device %s. Please try again in a moment.", self.name,
                )) from e
            raise
        # Invalidate counter fields so we re-read the committed values now
        # that we hold the lock.
        self.invalidate_recordset(['receipt_global_no', 'last_receipt_hash',
                                   'current_fiscal_day_id'])
        return self

    @api.model
    def _get_device_for_company(self, company, journal=None):
        """Resolve the active device for a company (journal override first)."""
        if journal and journal.l10n_zw_device_id and journal.l10n_zw_device_id.active:
            return journal.l10n_zw_device_id
        return self.env['l10n_zw.fdms.device'].search([
            ('company_id', '=', company.id),
            ('state', '=', 'registered'),
        ], limit=1)

    def _ensure_open_fiscal_day(self):
        """Return the open fiscal day, opening one (API + local) if needed.

        Must be called while holding _lock(). Never blocks on connectivity:
        if the OpenDay call fails, the day is still created locally and
        flagged for later server-side reconciliation.
        """
        self.ensure_one()
        day = self.current_fiscal_day_id
        if day and day.state == 'open':
            return day
        return self.env['l10n_zw.fiscal.day']._open_day(self)

    def _allocate_receipt_numbers(self):
        """Allocate the next (global_no, counter, day) triple. Lock required."""
        self.ensure_one()
        day = self._ensure_open_fiscal_day()
        global_no = self.receipt_global_no + 1
        counter = day.receipt_counter + 1
        return global_no, counter, day

    def _commit_receipt_numbers(self, global_no, counter, day, receipt_hash_b64):
        """Persist counter state after a successful signing. Lock required."""
        self.ensure_one()
        self.write({
            'receipt_global_no': global_no,
            'last_receipt_hash': receipt_hash_b64,
        })
        day.write({'receipt_counter': counter})

    # ------------------------------------------------------------------
    # Actions (buttons)
    # ------------------------------------------------------------------

    def action_register(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Register Device with ZIMRA"),
            'res_model': 'l10n_zw.fdms.register.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_device_id': self.id},
        }

    def action_get_config(self):
        self.ensure_one()
        error, data = self.env['l10n_zw.fdms.api']._call_fdms(
            self, 'GET', 'GetConfig')
        if error:
            raise UserError(_("GetConfig failed: %s", error.get('message', error)))
        self._apply_config(data)
        return self._notify(_("Device configuration refreshed."))

    def _apply_config(self, data):
        self.ensure_one()
        vals = {
            'config_json': data,
            'applicable_taxes': data.get('applicableTaxes'),
            'operating_mode': data.get('deviceOperatingMode'),
            'taxpayer_name': data.get('taxPayerName') or self.taxpayer_name,
            'taxpayer_tin': data.get('taxPayerTIN') or self.taxpayer_tin,
            'taxpayer_vat_number': data.get('vatNumber') or self.taxpayer_vat_number,
            'branch_name': data.get('deviceBranchName') or self.branch_name,
        }
        if data.get('qrUrl'):
            vals['qr_url'] = data['qrUrl']
        if data.get('taxPayerDayMaxHrs'):
            vals['tax_payer_day_max_hrs'] = data['taxPayerDayMaxHrs']
        if data.get('certificateValidTill'):
            vals['certificate_valid_till'] = fields.Datetime.to_datetime(
                data['certificateValidTill'].replace('Z', '').split('.')[0].replace('T', ' '))
        self.write(vals)

    def action_ping(self):
        self.ensure_one()
        error, data = self.env['l10n_zw.fdms.api']._call_fdms(self, 'POST', 'Ping')
        if error:
            raise UserError(_("Ping failed: %s", error.get('message', error)))
        return self._notify(_("Ping OK (operation %s).", data.get('operationID', '-')))

    def action_get_status(self):
        self.ensure_one()
        error, data = self.env['l10n_zw.fdms.api']._call_fdms(self, 'GET', 'GetStatus')
        if error:
            raise UserError(_("GetStatus failed: %s", error.get('message', error)))
        self.env['l10n_zw.fiscal.day']._apply_server_status(self, data)
        return self._notify(_(
            "Server status: %(status)s — last fiscal day %(day)s, last global receipt %(no)s.",
            status=data.get('fiscalDayStatus'),
            day=data.get('lastFiscalDayNo'),
            no=data.get('lastReceiptGlobalNo'),
        ))

    def action_resync(self):
        """Compare server counters with local state after a crash."""
        self.ensure_one()
        error, data = self.env['l10n_zw.fdms.api']._call_fdms(self, 'GET', 'GetStatus')
        if error:
            raise UserError(_("GetStatus failed: %s", error.get('message', error)))
        server_no = data.get('lastReceiptGlobalNo') or 0
        if server_no > self.receipt_global_no:
            raise UserError(_(
                "The FDMS server has receipts up to global number %(server)s but this "
                "device only knows %(local)s. This should never happen — contact "
                "support before issuing more receipts.",
                server=server_no, local=self.receipt_global_no,
            ))
        gap = self.receipt_global_no - server_no
        return self._notify(
            _("In sync with FDMS.") if not gap
            else _("%s receipt(s) signed locally are not yet on the server; the send "
                   "queue will submit them.", gap)
        )

    def action_open_day(self):
        self.ensure_one()
        self._lock()
        self._ensure_open_fiscal_day()
        return self._notify(_("Fiscal day %s is open.", self.current_fiscal_day_id.fiscal_day_no))

    def action_close_day(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Close Fiscal Day"),
            'res_model': 'l10n_zw.fdms.close.day.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_device_id': self.id},
        }

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Fiscal Documents"),
            'res_model': 'l10n_zw.fdms.document',
            'view_mode': 'list,form',
            'domain': [('device_id', '=', self.id)],
        }

    def action_view_fiscal_days(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Fiscal Days"),
            'res_model': 'l10n_zw.fiscal.day',
            'view_mode': 'list,form',
            'domain': [('device_id', '=', self.id)],
        }

    def _notify(self, message, sticky=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'message': message,
                'type': 'info',
                'sticky': sticky,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ------------------------------------------------------------------
    # Certificate renewal cron
    # ------------------------------------------------------------------

    def _cron_renew_certificates(self):
        cutoff = fields.Datetime.add(fields.Datetime.now(), days=30)
        devices = self.search([
            ('state', '=', 'registered'),
            ('mode', '!=', 'demo'),
            ('certificate_valid_till', '!=', False),
            ('certificate_valid_till', '<', cutoff),
        ])
        for device in devices:
            try:
                self.env['l10n_zw.fdms.api']._renew_certificate(device)
                self.env.cr.commit()
            except Exception:  # noqa: BLE001 - cron must not abort the batch
                _logger.exception("ZIMRA certificate renewal failed for device %s", device.name)
                self.env.cr.rollback()
