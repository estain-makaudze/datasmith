from odoo import _, api, models


class AccountMoveSend(models.AbstractModel):
    _inherit = 'account.move.send'

    @api.model
    def _is_zw_fdms_applicable(self, move):
        doc = move.l10n_zw_fdms_document_ids.sorted('id')[-1:]
        return bool(doc) and doc.state in ('signed', 'error')

    def _get_all_extra_edis(self) -> dict:
        # EXTENDS 'account'
        res = super()._get_all_extra_edis()
        res.update({'zw_fdms': {
            'label': _("Submit to ZIMRA (FDMS)"),
            'is_applicable': self._is_zw_fdms_applicable,
        }})
        return res

    def _call_web_service_before_invoice_pdf_render(self, invoices_data):
        # EXTENDS 'account'
        super()._call_web_service_before_invoice_pdf_render(invoices_data)
        documents = self.env['l10n_zw.fdms.document']
        for invoice, invoice_data in invoices_data.items():
            if 'zw_fdms' in invoice_data['extra_edis']:
                documents |= invoice.l10n_zw_fdms_document_ids
        if not documents:
            return
        # Trigger the queue; the invoice is already signed (QR is on the PDF
        # regardless), so a failed submission is a warning, not an error.
        documents.action_retry()
        for invoice, invoice_data in invoices_data.items():
            doc = invoice.l10n_zw_fdms_document_ids.sorted('id')[-1:]
            if doc and doc.state == 'error':
                invoice_data['error'] = {
                    'error_title': _("The document is signed but ZIMRA submission failed "
                                     "(it will be retried automatically):"),
                    'errors': [doc.errors or _("Unknown error")],
                }
        if self._can_commit():
            self.env.cr.commit()
