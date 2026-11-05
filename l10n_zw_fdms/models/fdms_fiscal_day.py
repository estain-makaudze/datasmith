import json
import logging
from collections import defaultdict
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import fdms_signing

_logger = logging.getLogger(__name__)

# receiptType -> (sales counter, tax counter, balance sign)
_COUNTER_MAP = {
    'FiscalInvoice': ('SaleByTax', 'SaleTaxByTax', 1),
    'CreditNote': ('CreditNoteByTax', 'CreditNoteTaxByTax', 1),
    'DebitNote': ('DebitNoteByTax', 'DebitNoteTaxByTax', 1),
}


class L10nZwFiscalDay(models.Model):
    _name = 'l10n_zw.fiscal.day'
    _description = 'ZIMRA Fiscal Day'
    _order = 'fiscal_day_no desc, id desc'

    device_id = fields.Many2one('l10n_zw.fdms.device', required=True, index=True, ondelete='restrict')
    company_id = fields.Many2one(related='device_id.company_id', store=True)
    fiscal_day_no = fields.Integer(required=True)
    opened_datetime = fields.Datetime(required=True)
    closed_datetime = fields.Datetime(copy=False)
    state = fields.Selection(
        [
            ('open', 'Open'),
            ('close_initiated', 'Closing'),
            ('closed', 'Closed'),
            ('close_failed', 'Close Failed'),
        ],
        default='open', required=True, copy=False, index=True,
    )
    server_synced = fields.Boolean(
        default=False,
        help="False while the OpenDay call has not been acknowledged by the "
             "FDMS server (day was opened locally while offline).",
    )
    receipt_counter = fields.Integer(
        default=0,
        help="Last used receiptCounter within this fiscal day.",
    )
    document_ids = fields.One2many('l10n_zw.fdms.document', 'fiscal_day_id')
    document_count = fields.Integer(compute='_compute_document_count')
    counters_json = fields.Json(copy=False, help="fiscalDayCounters as sent at close (audit).")
    close_operation_id = fields.Char(copy=False)
    close_error = fields.Html(copy=False, sanitize=True)

    _day_device_uniq = models.Constraint(
        'unique(device_id, fiscal_day_no)',
        "This fiscal day number already exists for this device.")

    def _compute_document_count(self):
        counts = dict(self.env['l10n_zw.fdms.document']._read_group(
            [('fiscal_day_id', 'in', self.ids)], ['fiscal_day_id'], ['__count']))
        for day in self:
            day.document_count = counts.get(day, 0)

    @api.depends('device_id.name', 'fiscal_day_no')
    def _compute_display_name(self):
        for day in self:
            day.display_name = f"{day.device_id.name} / Day {day.fiscal_day_no}"

    # ------------------------------------------------------------------
    # Open
    # ------------------------------------------------------------------

    @api.model
    def _open_day(self, device):
        """Open a new fiscal day (server + local). Device lock must be held.

        Non-blocking: if the OpenDay HTTP call fails, the day is created
        locally with server_synced=False and reconciled later by the send
        cron (the FDMS accepts retro-submission within 72 hours).
        """
        last = self.search([('device_id', '=', device.id)], order='fiscal_day_no desc', limit=1)
        if last and last.state in ('open', 'close_initiated'):
            raise UserError(_(
                "Fiscal day %s is still %s on device %s; it must be closed before "
                "opening a new one.", last.fiscal_day_no, last.state, device.name))
        opened = fields.Datetime.context_timestamp(device, fields.Datetime.now()).replace(tzinfo=None)
        next_day_no = (last.fiscal_day_no if last else 0) + 1
        server_synced = False
        error, data = self.env['l10n_zw.fdms.api']._call_fdms(
            device, 'POST', 'OpenDay',
            payload={
                'fiscalDayOpened': fdms_signing.format_receipt_date(opened),
                'fiscalDayNo': next_day_no,
            })
        if error:
            _logger.warning(
                "ZIMRA OpenDay failed on device %s (%s); opening day %s locally.",
                device.name, error, next_day_no)
        else:
            server_synced = True
            if data.get('fiscalDayNo'):
                next_day_no = data['fiscalDayNo']
        day = self.create({
            'device_id': device.id,
            'fiscal_day_no': next_day_no,
            'opened_datetime': opened,
            'server_synced': server_synced,
        })
        device.write({
            'current_fiscal_day_id': day.id,
            'last_receipt_hash': False,  # the hash chain restarts every fiscal day
        })
        return day

    def _retry_server_open(self):
        """Retry the OpenDay call for days opened while offline."""
        for day in self.filtered(lambda d: d.state == 'open' and not d.server_synced):
            error, _data = self.env['l10n_zw.fdms.api']._call_fdms(
                day.device_id, 'POST', 'OpenDay',
                payload={
                    'fiscalDayOpened': fdms_signing.format_receipt_date(day.opened_datetime),
                    'fiscalDayNo': day.fiscal_day_no,
                })
            if not error:
                day.server_synced = True

    # ------------------------------------------------------------------
    # Counters & close
    # ------------------------------------------------------------------

    def _compute_fiscal_day_counters(self):
        """Compute fiscalDayCounters from the day's signed documents.

        Always recomputed from the immutable submitted payloads so the
        counters provably match what was signed and sent.
        """
        self.ensure_one()
        # Sales and taxes are keyed per counter type: a sale and a credit note
        # over the same tax must yield separate counters, never net out.
        sales = defaultdict(Decimal)      # (counter_type, currency, taxID, percent) -> amount
        taxes = defaultdict(Decimal)      # (counter_type, currency, taxID, percent) -> tax amount
        balances = defaultdict(Decimal)   # (currency, moneyType) -> amount (this one does net)

        for doc in self.document_ids.filtered(lambda d: d.state in ('signed', 'sent')):
            payload = doc._get_payload()
            receipt = payload.get('receipt', payload)
            rtype = receipt['receiptType']
            sale_counter, tax_counter, _sign = _COUNTER_MAP[rtype]
            currency = receipt['receiptCurrency']
            for tax in receipt.get('receiptTaxes', []):
                key = (currency, tax['taxID'], tax.get('taxPercent'))
                sales[(sale_counter, *key)] += Decimal(str(tax['salesAmountWithTax']))
                taxes[(tax_counter, *key)] += Decimal(str(tax['taxAmount']))
            for payment in receipt.get('receiptPayments', []):
                balances[(currency, payment['moneyTypeCode'])] += \
                    Decimal(str(payment['paymentAmount']))

        counters = []
        for source in (sales, taxes):
            for (counter_type, currency, tax_id, percent), value in source.items():
                counters.append({
                    'fiscalCounterType': counter_type,
                    'fiscalCounterCurrency': currency,
                    'fiscalCounterTaxID': tax_id,
                    'fiscalCounterTaxPercent': percent,
                    'fiscalCounterValue': float(value),
                })
        for (currency, money_type), value in balances.items():
            counters.append({
                'fiscalCounterType': 'BalanceByMoneyType',
                'fiscalCounterCurrency': currency,
                'fiscalCounterMoneyType': money_type,
                'fiscalCounterValue': float(value),
            })
        return [c for c in counters if fdms_signing.to_cents(c['fiscalCounterValue']) != '0']

    def action_close(self, force=False):
        """Sign and submit CloseDay. Async on the server side: poll GetStatus."""
        self.ensure_one()
        if self.state not in ('open', 'close_failed'):
            raise UserError(_("Fiscal day %s is not open.", self.fiscal_day_no))
        unsent = self.document_ids.filtered(lambda d: d.state == 'signed')
        if unsent and not force:
            raise UserError(_(
                "%s document(s) of this fiscal day have not been submitted to ZIMRA "
                "yet. Submit them first (or force-close from the wizard).", len(unsent)))

        device = self.device_id
        counters = self._compute_fiscal_day_counters()
        source = fdms_signing.build_fiscal_day_signature_string(
            device.device_id, self.fiscal_day_no,
            self.opened_datetime.date(), counters).upper()
        _digest, hash_b64 = fdms_signing.sha256_b64(source)
        # certificate.key._sign hashes internally with SHA-256, so we sign the
        # source string itself (equivalent to signing the precomputed hash).
        signature = device.key_id._sign(source, hashing_algorithm='sha256', formatting='base64').decode()

        error, data = self.env['l10n_zw.fdms.api']._call_fdms(
            device, 'POST', 'CloseDay',
            payload={
                'fiscalDayNo': self.fiscal_day_no,
                'fiscalDayCounters': counters,
                'fiscalDayDeviceSignature': {'hash': hash_b64, 'signature': signature},
                'receiptCounter': self.receipt_counter,
            })
        if error:
            self.write({
                'state': 'close_failed',
                'close_error': _("CloseDay call failed: %s", error),
                'counters_json': counters,
            })
            return False
        self.write({
            'state': 'close_initiated',
            'counters_json': counters,
            'close_operation_id': data.get('operationID'),
            'close_error': False,
        })
        return True

    def _poll_close_status(self):
        for day in self.filtered(lambda d: d.state == 'close_initiated'):
            error, data = self.env['l10n_zw.fdms.api']._call_fdms(
                day.device_id, 'GET', 'GetStatus')
            if error:
                continue
            day._apply_server_status(day.device_id, data, polling_day=day)

    @api.model
    def _apply_server_status(self, device, data, polling_day=None):
        """Apply a GetStatus response to the polled/current day."""
        status = data.get('fiscalDayStatus')
        day = polling_day or device.current_fiscal_day_id
        if not day:
            return
        if status == 'FiscalDayClosed' and day.state in ('close_initiated', 'open', 'close_failed'):
            day.write({
                'state': 'closed',
                'closed_datetime': fields.Datetime.now(),
            })
            if device.current_fiscal_day_id == day:
                device.current_fiscal_day_id = False
        elif status == 'FiscalDayCloseFailed':
            day.write({
                'state': 'close_failed',
                'close_error': _("FDMS reported the day close failed (error code: %s). "
                                 "Manual reconciliation may be required.",
                                 data.get('fiscalDayClosingErrorCode', '-')),
            })

    # ------------------------------------------------------------------
    # Auto-close cron
    # ------------------------------------------------------------------

    @api.model
    def _cron_auto_close(self):
        """Close aging fiscal days and poll pending close operations."""
        self.search([('state', '=', 'close_initiated')])._poll_close_status()
        now = fields.Datetime.now()
        for day in self.search([('state', '=', 'open')]):
            max_hrs = day.device_id.tax_payer_day_max_hrs or 24
            age_hrs = (now - day.opened_datetime).total_seconds() / 3600
            # Close ~2h before the ZIMRA limit; earliest after 20h for a 24h day.
            if age_hrs < max(max_hrs - 2, 1):
                continue
            if day.document_ids.filtered(lambda d: d.state == 'signed'):
                _logger.warning(
                    "ZIMRA fiscal day %s on device %s is %d hours old but still has "
                    "unsent documents; not auto-closing.",
                    day.fiscal_day_no, day.device_id.name, int(age_hrs))
                continue
            try:
                day.action_close()
                self.env.cr.commit()
            except Exception:  # noqa: BLE001 - cron must not abort the batch
                _logger.exception("Auto-close failed for fiscal day %s", day.fiscal_day_no)
                self.env.cr.rollback()
