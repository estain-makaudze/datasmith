import base64
from collections import defaultdict
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import fdms_signing

FISCAL_MOVE_TYPES = ('out_invoice', 'out_refund')


class AccountMove(models.Model):
    _inherit = 'account.move'

    l10n_zw_fdms_document_ids = fields.One2many(
        'l10n_zw.fdms.document', 'move_id', copy=False)
    l10n_zw_fdms_state = fields.Selection(
        [
            ('signed', 'Signed / To Send'),
            ('ambiguous', 'Submission Unconfirmed'),
            ('sent', 'Sent to ZIMRA'),
            ('error', 'Submission Error'),
        ],
        compute='_compute_l10n_zw_fdms_fields', string="ZIMRA Status",
    )
    l10n_zw_is_fiscalised = fields.Boolean(compute='_compute_l10n_zw_fdms_fields')
    l10n_zw_receipt_global_no = fields.Integer(
        compute='_compute_l10n_zw_fdms_fields', string="Fiscal Receipt No")
    l10n_zw_fiscal_day_no = fields.Integer(compute='_compute_l10n_zw_fdms_fields')
    l10n_zw_receipt_date = fields.Datetime(compute='_compute_l10n_zw_fdms_fields')
    l10n_zw_device_serial = fields.Char(compute='_compute_l10n_zw_fdms_fields')
    l10n_zw_verification_code = fields.Char(compute='_compute_l10n_zw_fdms_fields')
    l10n_zw_qr_data = fields.Char(compute='_compute_l10n_zw_fdms_fields')
    l10n_zw_qr_image = fields.Binary(compute='_compute_l10n_zw_qr_image')
    l10n_zw_validation_color = fields.Selection(
        [('green', 'Clean'), ('grey', 'Grey'), ('yellow', 'Yellow'), ('red', 'Red')],
        compute='_compute_l10n_zw_fdms_fields',
    )

    @api.depends('l10n_zw_fdms_document_ids.state',
                 'l10n_zw_fdms_document_ids.validation_color')
    def _compute_l10n_zw_fdms_fields(self):
        for move in self:
            doc = move.l10n_zw_fdms_document_ids.sorted('id')[-1:]
            move.l10n_zw_is_fiscalised = bool(doc)
            move.l10n_zw_fdms_state = doc.state or False
            move.l10n_zw_receipt_global_no = doc.receipt_global_no
            move.l10n_zw_fiscal_day_no = doc.fiscal_day_id.fiscal_day_no
            move.l10n_zw_receipt_date = doc.receipt_date
            move.l10n_zw_device_serial = doc.device_id.serial_number
            move.l10n_zw_verification_code = (
                fdms_signing.format_verification_code(doc.verification_code)
                if doc.verification_code else False)
            move.l10n_zw_qr_data = doc.qr_data
            move.l10n_zw_validation_color = doc.validation_color

    @api.depends('l10n_zw_qr_data')
    def _compute_l10n_zw_qr_image(self):
        for move in self:
            if move.l10n_zw_qr_data:
                move.l10n_zw_qr_image = base64.b64encode(
                    self.env['ir.actions.report'].barcode(
                        'QR', move.l10n_zw_qr_data, width=160, height=160))
            else:
                move.l10n_zw_qr_image = False

    # ------------------------------------------------------------------
    # Posting hook
    # ------------------------------------------------------------------

    def _l10n_zw_fdms_applicable(self):
        self.ensure_one()
        return (
            self.is_sale_document(include_receipts=False)
            and self.move_type in FISCAL_MOVE_TYPES
            and self.company_id.country_code == 'ZW'
            and bool(self._l10n_zw_get_device())
        )

    def _l10n_zw_get_device(self):
        self.ensure_one()
        return self.env['l10n_zw.fdms.device']._get_device_for_company(
            self.company_id, journal=self.journal_id)

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted:
            if move._l10n_zw_fdms_applicable() and not move.l10n_zw_fdms_document_ids:
                move._l10n_zw_pre_checks()
                move._l10n_zw_fiscalise()
        # Kick the send queue so online submissions are near-instant.
        if any(m.l10n_zw_fdms_document_ids for m in posted):
            cron = self.env.ref('l10n_zw_fdms.ir_cron_send_documents', raise_if_not_found=False)
            if cron:
                cron._trigger()
        return posted

    def _l10n_zw_pre_checks(self):
        self.ensure_one()
        device = self._l10n_zw_get_device()
        errors = []
        product_lines = self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product')
        for line in product_lines:
            zw_taxes = line.tax_ids.filtered('l10n_zw_tax_id')
            if not zw_taxes:
                errors.append(_(
                    "Line '%s' has no tax with a ZIMRA Tax ID. Every line of a "
                    "fiscal invoice needs exactly one ZIMRA-mapped tax.", line.name))
            elif len(zw_taxes) > 1:
                errors.append(_("Line '%s' has more than one ZIMRA-mapped tax.", line.name))
            elif device.applicable_taxes:
                valid_ids = {t.get('taxID') for t in device.applicable_taxes}
                if zw_taxes.l10n_zw_tax_id not in valid_ids:
                    errors.append(_(
                        "Tax '%(tax)s' (ZIMRA ID %(tid)s) is not in the device's "
                        "applicable taxes.", tax=zw_taxes.name, tid=zw_taxes.l10n_zw_tax_id))
        partner = self.commercial_partner_id
        if partner.is_company and not partner.l10n_zw_tin:
            errors.append(_(
                "%s is a company: B2B fiscal invoices must carry the buyer's "
                "10-digit ZIMRA TIN (Public Notice 30 of 2025). Set it on the "
                "partner.", partner.name))
        if self.move_type == 'out_refund':
            original = self.reversed_entry_id
            original_doc = original.l10n_zw_fdms_document_ids.sorted('id')[-1:]
            if not original_doc:
                errors.append(_(
                    "Credit notes must reference a fiscalised invoice: %s has no "
                    "fiscal document. Link the credit note to its original invoice "
                    "(Reverse from the invoice).", original.name or _('no original invoice set')))
        if not self.currency_id.name or len(self.currency_id.name) != 3:
            errors.append(_("Currency %s has no valid ISO code.", self.currency_id.name))
        if errors:
            raise UserError(_(
                "This document cannot be fiscalised with ZIMRA:\n- %s",
                '\n- '.join(errors)))

    # ------------------------------------------------------------------
    # Payload building
    # ------------------------------------------------------------------

    def _l10n_zw_get_money_type(self):
        """FDMS moneyTypeCode for this document. Overridable by bridges."""
        self.ensure_one()
        return 'Credit'

    def _l10n_zw_fiscalise(self):
        self.ensure_one()
        device = self._l10n_zw_get_device()
        sign = -1 if self.move_type == 'out_refund' else 1
        document_type = 'CreditNote' if self.move_type == 'out_refund' else 'FiscalInvoice'

        product_lines = self.invoice_line_ids.filtered(
            lambda l: l.display_type == 'product')

        # Tax amounts per tax, from the actual tax journal items.
        tax_amounts = defaultdict(Decimal)
        for line in self.line_ids.filtered('tax_line_id'):
            tax = line.tax_line_id
            if tax.l10n_zw_tax_id:
                tax_amounts[tax] += Decimal(str(abs(line.amount_currency)))

        lines = []
        sales_with_tax = defaultdict(Decimal)
        for index, line in enumerate(product_lines, start=1):
            tax = line.tax_ids.filtered('l10n_zw_tax_id')[:1]
            total = Decimal(str(line.price_total)) * sign
            sales_with_tax[tax] += total
            line_vals = {
                'receiptLineType': 'Sale',
                'receiptLineNo': index,
                'receiptLineName': (line.name or line.product_id.display_name or '/')[:200],
                'receiptLineQuantity': line.quantity * sign,
                'receiptLineTotal': float(total),
                'taxID': tax.l10n_zw_tax_id,
                'taxPercent': None if tax.l10n_zw_is_exempt else round(tax.amount, 2),
            }
            if tax.l10n_zw_tax_code:
                line_vals['taxCode'] = tax.l10n_zw_tax_code
            hs_code = getattr(line.product_id, 'hs_code', False)
            if hs_code:
                line_vals['receiptLineHSCode'] = hs_code[:8]
            if line.quantity:
                line_vals['receiptLinePrice'] = float(
                    (total / Decimal(str(line.quantity))).quantize(Decimal('0.0001')))
            if line_vals['taxPercent'] is None:
                del line_vals['taxPercent']
            lines.append(line_vals)

        taxes = []
        for tax, amount_with_tax in sales_with_tax.items():
            taxes.append({
                'taxID': tax.l10n_zw_tax_id,
                'taxCode': tax.l10n_zw_tax_code or None,
                'taxPercent': tax._l10n_zw_signature_percent() or None,
                'taxAmount': tax_amounts.get(tax, Decimal('0')) * sign,
                'salesAmountWithTax': amount_with_tax,
            })
        taxes.sort(key=lambda t: t['taxID'])

        total = Decimal(str(self.amount_total)) * sign
        payments = [{
            'moneyTypeCode': self._l10n_zw_get_money_type(),
            'paymentAmount': float(total),
        }]

        record_values = {
            'record': self,
            'device': device,
            'document_type': document_type,
            'currency': self.currency_id.name,
            'invoice_no': (self.name or '')[:50],
            'tax_inclusive': True,
            'lines': lines,
            'taxes': taxes,
            'payments': payments,
            'total': total,
            'buyer_data': self.commercial_partner_id._l10n_zw_buyer_data(),
            'notes': self.ref or None,
        }
        if document_type == 'CreditNote':
            original_doc = self.reversed_entry_id.l10n_zw_fdms_document_ids.sorted('id')[-1:]
            record_values['credit_debit_note'] = {'original_document_id': original_doc.id}
            record_values['notes'] = self.ref or _("Credit note for %s", self.reversed_entry_id.name)
        return self.env['l10n_zw.fdms.document']._create_for_record(record_values)

    # ------------------------------------------------------------------
    # Immutability
    # ------------------------------------------------------------------

    @api.depends('l10n_zw_fdms_document_ids')
    def _compute_show_reset_to_draft_button(self):
        super()._compute_show_reset_to_draft_button()
        for move in self:
            if move.l10n_zw_fdms_document_ids:
                move.show_reset_to_draft_button = False

    def button_draft(self):
        for move in self:
            if move.l10n_zw_fdms_document_ids:
                raise UserError(_(
                    "%s has been fiscalised with ZIMRA and cannot be reset to "
                    "draft. Issue a credit note to correct it.", move.name))
        return super().button_draft()

    def action_l10n_zw_retry_send(self):
        self.l10n_zw_fdms_document_ids.action_retry()
