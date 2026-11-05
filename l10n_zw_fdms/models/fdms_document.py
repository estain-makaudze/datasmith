import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import fdms_signing

_logger = logging.getLogger(__name__)

# Exponential backoff steps (minutes) for failed submissions.
_BACKOFF_MINUTES = [1, 5, 15, 60, 240, 720]


class L10nZwFdmsDocument(models.Model):
    _name = 'l10n_zw.fdms.document'
    _description = 'ZIMRA Fiscal Document'
    _order = 'receipt_global_no desc, id desc'

    company_id = fields.Many2one('res.company', required=True, index=True)
    device_id = fields.Many2one('l10n_zw.fdms.device', required=True, index=True, ondelete='restrict')
    fiscal_day_id = fields.Many2one('l10n_zw.fiscal.day', required=True, index=True, ondelete='restrict')
    move_id = fields.Many2one('account.move', index=True, ondelete='restrict')
    document_type = fields.Selection(
        [
            ('FiscalInvoice', 'Fiscal Invoice'),
            ('CreditNote', 'Credit Note'),
            ('DebitNote', 'Debit Note'),
        ],
        required=True,
    )
    state = fields.Selection(
        [
            ('signed', 'Signed / To Send'),
            ('ambiguous', 'Submission Unconfirmed'),
            ('sent', 'Sent'),
            ('error', 'Error'),
        ],
        default='signed', required=True, copy=False, index=True,
    )

    # --- chain fields: written once at signing, immutable afterwards ---
    receipt_global_no = fields.Integer(readonly=True)
    receipt_counter = fields.Integer(readonly=True)
    receipt_date = fields.Datetime(readonly=True,
                                   help="Naive local device time used in the signature.")
    currency_code = fields.Char(readonly=True)
    receipt_total = fields.Float(readonly=True)
    invoice_no = fields.Char(readonly=True)
    previous_hash = fields.Char(readonly=True)
    receipt_hash = fields.Char(readonly=True, help="Base64 SHA-256 of the signature string.")
    device_signature = fields.Char(readonly=True, help="Base64 device signature.")
    attachment_id = fields.Many2one('ir.attachment', readonly=True,
                                    help="Immutable JSON payload as signed/submitted.")

    # --- server response ---
    receipt_id_zimra = fields.Char(string="FDMS Receipt ID", copy=False,
                                   help="Server-assigned receiptID; credit notes must reference it.")
    operation_id = fields.Char(copy=False)
    server_signature = fields.Json(copy=False)
    validation_errors = fields.Json(copy=False)
    validation_color = fields.Selection(
        [('green', 'Clean'), ('grey', 'Grey'), ('yellow', 'Yellow'), ('red', 'Red')],
        copy=False,
    )
    errors = fields.Html(copy=False, sanitize=True)

    # --- QR / verification ---
    qr_data = fields.Char(readonly=True)
    verification_code = fields.Char(readonly=True)

    # --- retry machinery ---
    attempts = fields.Integer(default=0, copy=False)
    next_attempt_at = fields.Datetime(copy=False)

    _receipt_global_no_uniq = models.Constraint(
        'unique(device_id, receipt_global_no)',
        "Duplicate receipt global number on this device — the fiscal chain is corrupted.")

    @api.depends('document_type', 'receipt_global_no')
    def _compute_display_name(self):
        for doc in self:
            doc.display_name = f"{doc.document_type} #{doc.receipt_global_no or '?'}"

    @api.ondelete(at_uninstall=False)
    def _never_unlink_fiscal_documents(self):
        if any(doc.receipt_global_no for doc in self):
            raise UserError(_(
                "Fiscal documents are part of the ZIMRA hash chain and can never "
                "be deleted."))

    def _get_payload(self):
        self.ensure_one()
        return json.loads(self.attachment_id.raw.decode())

    def _get_record(self):
        """The business record this document fiscalises. Bridges extend this."""
        self.ensure_one()
        return self.move_id

    # ------------------------------------------------------------------
    # Creation & signing
    # ------------------------------------------------------------------

    @api.model
    def _create_for_record(self, record_values):
        """Sign a receipt and create the fiscal document for any source record.

        This is the single entry point of the fiscalisation engine; the
        account.move integration and any future bridge (POS, e-commerce)
        call it with a normalised dict:

        record_values = {
            'record': <recordset of the source document>,
            'device': <l10n_zw.fdms.device>,
            'document_type': 'FiscalInvoice' | 'CreditNote' | 'DebitNote',
            'currency': 'USD',
            'invoice_no': str,
            'tax_inclusive': bool,
            'lines': [{'receiptLineType', 'receiptLineName', 'receiptLineQuantity',
                       'receiptLinePrice', 'receiptLineTotal', 'taxID',
                       'taxCode', 'taxPercent', 'receiptLineHSCode'}],
            'taxes': [{'taxID', 'taxCode', 'taxPercent' (None for exempt),
                       'taxAmount', 'salesAmountWithTax'}],   # Decimal-safe values
            'payments': [{'moneyTypeCode', 'paymentAmount'}],
            'total': amount,
            'buyer_data': dict | None,
            'notes': str | None,
            'credit_debit_note': {'original_document_id': id} | None,
            'extra_document_vals': dict | None,   # bridge FK, e.g. pos_order_id
        }

        Must be called inside the posting transaction. Locks the device row:
        the chain state committed here is atomic with the source document.
        """
        device = record_values['device']
        device._lock()
        global_no, counter, day = device._allocate_receipt_numbers()

        receipt_date = fields.Datetime.context_timestamp(
            device, fields.Datetime.now()).replace(tzinfo=None)
        previous_hash = device.last_receipt_hash if counter > 1 else None

        signature_taxes = [{
            'taxID': tax['taxID'],
            'taxPercent': tax['taxPercent'],
            'taxAmount': tax['taxAmount'],
            'salesAmountWithTax': tax['salesAmountWithTax'],
        } for tax in record_values['taxes']]

        source = fdms_signing.build_receipt_signature_string(
            device.device_id,
            record_values['document_type'],
            record_values['currency'],
            global_no,
            receipt_date,
            record_values['total'],
            signature_taxes,
            previous_receipt_hash_b64=previous_hash,
        )
        _digest, hash_b64 = fdms_signing.sha256_b64(source)
        # certificate.key._sign hashes internally (SHA-256) before signing, so
        # passing the source string yields the signature of its SHA-256 hash.
        signature_b64 = device.key_id._sign(
            source, hashing_algorithm='sha256', formatting='base64').decode()

        verification_code = fdms_signing.compute_verification_code(signature_b64)
        qr_data = fdms_signing.build_qr_data(
            device.qr_url, device.device_id, receipt_date, global_no, signature_b64)

        receipt = {
            'receiptType': record_values['document_type'],
            'receiptCurrency': record_values['currency'],
            'receiptCounter': counter,
            'receiptGlobalNo': global_no,
            'invoiceNo': record_values['invoice_no'],
            'receiptDate': fdms_signing.format_receipt_date(receipt_date),
            'receiptLinesTaxInclusive': record_values.get('tax_inclusive', True),
            'receiptLines': record_values['lines'],
            'receiptTaxes': [{
                'taxID': tax['taxID'],
                **({'taxCode': tax['taxCode']} if tax.get('taxCode') else {}),
                **({'taxPercent': float(tax['taxPercent'])} if tax.get('taxPercent') not in (None, '') else {}),
                'taxAmount': float(tax['taxAmount']),
                'salesAmountWithTax': float(tax['salesAmountWithTax']),
            } for tax in record_values['taxes']],
            'receiptPayments': record_values['payments'],
            'receiptTotal': float(record_values['total']),
            'receiptPrintForm': 'InvoiceA4',
            'receiptDeviceSignature': {'hash': hash_b64, 'signature': signature_b64},
        }
        if record_values.get('buyer_data'):
            receipt['buyerData'] = record_values['buyer_data']
        if record_values.get('notes'):
            receipt['receiptNotes'] = record_values['notes']
        # creditDebitNote is NOT part of the device signature; it is late-bound
        # at send time from the original document's server-assigned receiptID.

        record = record_values['record']
        document = self.create({
            'company_id': device.company_id.id,
            'device_id': device.id,
            'fiscal_day_id': day.id,
            'move_id': record.id if record._name == 'account.move' else False,
            'document_type': record_values['document_type'],
            'receipt_global_no': global_no,
            'receipt_counter': counter,
            'receipt_date': receipt_date,
            'currency_code': record_values['currency'],
            'receipt_total': float(record_values['total']),
            'invoice_no': record_values['invoice_no'],
            'previous_hash': previous_hash,
            'receipt_hash': hash_b64,
            'device_signature': signature_b64,
            'verification_code': verification_code,
            'qr_data': qr_data,
            **(record_values.get('extra_document_vals') or {}),
        })
        document.attachment_id = self.env['ir.attachment'].create({
            'name': f'zimra_receipt_{device.device_id}_{global_no}.json',
            'raw': json.dumps({'receipt': receipt}, indent=2).encode(),
            'res_model': self._name,
            'res_id': document.id,
            'mimetype': 'application/json',
        })
        if record_values.get('credit_debit_note'):
            document.write({'l10n_zw_original_document_id':
                            record_values['credit_debit_note']['original_document_id']})
        device._commit_receipt_numbers(global_no, counter, day, hash_b64)
        return document

    # Reference to the original fiscalised document (credit/debit notes only).
    l10n_zw_original_document_id = fields.Many2one(
        'l10n_zw.fdms.document', string="Original Fiscal Document", copy=False, index=True)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    @api.model
    def trigger_next_batch(self):
        """Cron entry point: submit pending documents, then self-reschedule."""
        retry_needed = False
        devices = self.env['l10n_zw.fdms.device'].search([('state', '=', 'registered')])
        for device in devices:
            try:
                retry_needed |= self._send_pending(device)
                self.env.cr.commit()
            except Exception:  # noqa: BLE001 - one device must not poison the rest
                _logger.exception("ZIMRA send batch failed for device %s", device.name)
                self.env.cr.rollback()
                retry_needed = True
        if retry_needed:
            cron = self.env.ref('l10n_zw_fdms.ir_cron_send_documents', raise_if_not_found=False)
            if cron:
                cron._trigger(at=fields.Datetime.add(fields.Datetime.now(), minutes=2))

    def _send_pending(self, device):
        """Submit this device's queue in strict chain order.

        Returns True when a retry should be scheduled. Stops at the first
        transport failure: receipt N+1 must never reach the server before
        receipt N (RCPT011).
        """
        api_model = self.env['l10n_zw.fdms.api']
        now = fields.Datetime.now()

        # Reconcile unconfirmed submissions before sending anything else.
        ambiguous = self.search([
            ('device_id', '=', device.id), ('state', '=', 'ambiguous')],
            order='receipt_global_no')
        if ambiguous:
            error, status = api_model._call_fdms(device, 'GET', 'GetStatus')
            if error:
                return True
            confirmed_no = status.get('lastReceiptGlobalNo') or 0
            for doc in ambiguous:
                if doc.receipt_global_no <= confirmed_no:
                    # It did reach the server; mark sent without receiptID
                    # (recoverable from the FDMS portal if ever needed).
                    doc.write({'state': 'sent', 'errors': False})
                else:
                    doc.write({'state': 'signed'})

        # Retry OpenDay for days opened while offline.
        device.current_fiscal_day_id.filtered(
            lambda d: not d.server_synced)._retry_server_open()
        if device.current_fiscal_day_id and not device.current_fiscal_day_id.server_synced:
            return True

        pending = self.search([
            ('device_id', '=', device.id),
            '|',
            ('state', '=', 'signed'),
            '&', ('state', '=', 'error'), ('next_attempt_at', '<=', now),
        ], order='receipt_global_no')
        # Never submit ahead of an errored/backing-off earlier receipt.
        blocked = self.search([
            ('device_id', '=', device.id),
            ('state', '=', 'error'),
            ('next_attempt_at', '>', now),
        ], order='receipt_global_no', limit=1)
        if blocked:
            pending = pending.filtered(lambda d: d.receipt_global_no < blocked.receipt_global_no)

        retry_needed = bool(blocked)
        for doc in pending:
            payload = doc._get_payload()
            # Late-bind the credit/debit note reference.
            if doc.document_type in ('CreditNote', 'DebitNote'):
                original = doc.l10n_zw_original_document_id
                if not original or original.state != 'sent' or not original.receipt_id_zimra:
                    doc._register_failure(_(
                        "The original fiscal invoice has not been accepted by ZIMRA "
                        "yet; this note will be submitted after it."))
                    return True
                payload['receipt']['creditDebitNote'] = {
                    'receiptID': int(original.receipt_id_zimra)
                    if original.receipt_id_zimra.isdigit() else original.receipt_id_zimra,
                    'deviceID': device.device_id,
                    'receiptGlobalNo': original.receipt_global_no,
                    'fiscalDayNo': original.fiscal_day_id.fiscal_day_no,
                }

            error, data = api_model._call_fdms(
                device, 'POST', 'SubmitReceipt', payload=payload)
            if error:
                if error.get('code') == 'TIM':
                    doc.write({'state': 'ambiguous',
                               'errors': _("Timeout: submission outcome unknown; it will "
                                           "be verified against the server before retrying.")})
                else:
                    doc._register_failure(error.get('message') or str(error))
                return True
            doc._register_success(data)
        return retry_needed

    def _register_success(self, data):
        self.ensure_one()
        validation_errors = data.get('validationErrors') or []
        color = 'green'
        colors = {str(e.get('validationErrorColor', '')).lower() for e in validation_errors}
        for level in ('red', 'yellow', 'grey'):
            if level in colors:
                color = level
                break
        self.write({
            'state': 'sent',
            'receipt_id_zimra': str(data.get('receiptID', '')),
            'operation_id': data.get('operationID'),
            'server_signature': data.get('receiptServerSignature'),
            'validation_errors': validation_errors,
            'validation_color': color,
            'errors': False,
            'next_attempt_at': False,
        })
        if color == 'red':
            self._notify_red_validation()

    def _register_failure(self, message):
        self.ensure_one()
        backoff = _BACKOFF_MINUTES[min(self.attempts, len(_BACKOFF_MINUTES) - 1)]
        self.write({
            'state': 'error',
            'errors': message,
            'attempts': self.attempts + 1,
            'next_attempt_at': fields.Datetime.add(fields.Datetime.now(), minutes=backoff),
        })

    def _notify_red_validation(self):
        """Red validation errors block the fiscal day close — alert accounting."""
        self.ensure_one()
        record = self._get_record()
        if record and hasattr(record, 'activity_schedule'):
            record.activity_schedule(
                'mail.mail_activity_data_warning',
                summary=_("ZIMRA rejected this document (RED validation error)"),
                note=_(
                    "ZIMRA FDMS accepted receipt %(no)s with RED validation errors: "
                    "%(errors)s. The fiscal day cannot auto-close. A correcting "
                    "credit note is likely required (fiscalised receipts cannot be "
                    "resubmitted).",
                    no=self.receipt_global_no,
                    errors=', '.join(str(e.get('validationErrorCode', '?'))
                                     for e in (self.validation_errors or [])),
                ),
            )

    def action_retry(self):
        """Manual retry button: clear backoff and trigger the queue."""
        self.filtered(lambda d: d.state in ('error', 'ambiguous', 'signed')).write({
            'next_attempt_at': False,
            'state': 'signed',
        })
        self.trigger_next_batch()
