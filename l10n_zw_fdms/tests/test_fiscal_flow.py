from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestZimraFiscalFlow(AccountTestInvoicingCommon):

    @classmethod
    @AccountTestInvoicingCommon.setup_country('zw')
    def setUpClass(cls):
        super().setUpClass()
        cls.device = cls.env['l10n_zw.fdms.device'].create({
            'name': 'Test Device',
            'company_id': cls.env.company.id,
            'device_id': 321,
            'serial_number': 'SN-TEST-01',
            'mode': 'demo',
            'model_name': 'Odoo',
            'model_version': '19.0',
        })
        cls.env['l10n_zw.fdms.api']._register_device(cls.device)
        cls.tax_155 = cls.env['account.tax'].create({
            'name': 'VAT 15.5% (test)',
            'amount': 15.5,
            'type_tax_use': 'sale',
            'l10n_zw_tax_id': 515,
            'l10n_zw_tax_code': 'A',
            'company_id': cls.env.company.id,
        })

    def _create_invoice(self, price=100.0, move_type='out_invoice', **kwargs):
        move = self.env['account.move'].create({
            'move_type': move_type,
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [Command.create({
                'product_id': self.product_a.id,
                'quantity': 1,
                'price_unit': price,
                'tax_ids': [Command.set(self.tax_155.ids)],
            })],
            **kwargs,
        })
        return move

    def test_device_registered_demo(self):
        self.assertEqual(self.device.state, 'registered')
        self.assertTrue(self.device.key_id)
        self.assertTrue(self.device.certificate_id)
        self.assertTrue(self.device.applicable_taxes)

    def test_post_invoice_creates_signed_document(self):
        move = self._create_invoice()
        move.action_post()
        doc = move.l10n_zw_fdms_document_ids
        self.assertEqual(len(doc), 1)
        self.assertEqual(doc.state, 'signed')
        self.assertEqual(doc.document_type, 'FiscalInvoice')
        self.assertEqual(doc.receipt_global_no, 1)
        self.assertEqual(doc.receipt_counter, 1)
        self.assertFalse(doc.previous_hash)
        self.assertEqual(len(doc.verification_code), 16)
        self.assertTrue(doc.qr_data.startswith(self.device.qr_url))
        self.assertTrue(doc.attachment_id)
        payload = doc._get_payload()['receipt']
        self.assertEqual(payload['receiptType'], 'FiscalInvoice')
        self.assertEqual(payload['receiptGlobalNo'], 1)
        self.assertEqual(payload['receiptTaxes'][0]['taxID'], 515)
        self.assertAlmostEqual(payload['receiptTotal'], move.amount_total, places=2)

    def test_chain_and_send(self):
        move1 = self._create_invoice()
        move1.action_post()
        move2 = self._create_invoice(price=50.0)
        move2.action_post()
        doc1 = move1.l10n_zw_fdms_document_ids
        doc2 = move2.l10n_zw_fdms_document_ids
        self.assertEqual(doc2.receipt_global_no, 2)
        self.assertEqual(doc2.receipt_counter, 2)
        self.assertEqual(doc2.previous_hash, doc1.receipt_hash)
        self.assertEqual(self.device.receipt_global_no, 2)
        self.assertEqual(self.device.last_receipt_hash, doc2.receipt_hash)

        (doc1 | doc2)._send_pending(self.device)
        self.assertEqual(doc1.state, 'sent')
        self.assertEqual(doc2.state, 'sent')
        self.assertTrue(doc1.receipt_id_zimra)
        self.assertEqual(doc1.validation_color, 'green')

    def test_credit_note_flow(self):
        move = self._create_invoice()
        move.action_post()
        move.l10n_zw_fdms_document_ids._send_pending(self.device)

        reversal = move._reverse_moves(default_values_list=[{
            'invoice_date': move.invoice_date,
        }])
        reversal.action_post()
        cn_doc = reversal.l10n_zw_fdms_document_ids
        self.assertEqual(cn_doc.document_type, 'CreditNote')
        self.assertEqual(cn_doc.l10n_zw_original_document_id,
                         move.l10n_zw_fdms_document_ids)
        payload = cn_doc._get_payload()['receipt']
        self.assertLess(payload['receiptTotal'], 0)
        cn_doc._send_pending(self.device)
        self.assertEqual(cn_doc.state, 'sent')

        # Sale and credit note must produce separate counters, never net out.
        counters = self.device.current_fiscal_day_id._compute_fiscal_day_counters()
        by_type = {c['fiscalCounterType']: c['fiscalCounterValue'] for c in counters}
        self.assertGreater(by_type.get('SaleByTax', 0), 0)
        self.assertLess(by_type.get('CreditNoteByTax', 0), 0)
        self.assertNotIn('BalanceByMoneyType', by_type)  # payments net to zero

    def test_credit_note_without_fiscalised_original_blocked(self):
        move = self._create_invoice(move_type='out_refund')
        with self.assertRaises(UserError):
            move.action_post()

    def test_unmapped_tax_blocks_posting(self):
        bad_tax = self.env['account.tax'].create({
            'name': 'No ZIMRA id',
            'amount': 15.0,
            'type_tax_use': 'sale',
            'company_id': self.env.company.id,
        })
        move = self._create_invoice()
        move.invoice_line_ids.tax_ids = [Command.set(bad_tax.ids)]
        with self.assertRaises(UserError):
            move.action_post()

    def test_b2b_requires_tin(self):
        self.partner_a.write({'is_company': True, 'l10n_zw_tin': False})
        move = self._create_invoice()
        with self.assertRaises(UserError):
            move.action_post()
        self.partner_a.l10n_zw_tin = '1234567890'
        move.action_post()
        payload = move.l10n_zw_fdms_document_ids._get_payload()['receipt']
        self.assertEqual(payload['buyerData']['buyerTIN'], '1234567890')

    def test_reset_to_draft_blocked(self):
        move = self._create_invoice()
        move.action_post()
        with self.assertRaises(UserError):
            move.button_draft()

    def test_document_cannot_be_deleted(self):
        move = self._create_invoice()
        move.action_post()
        with self.assertRaises(UserError):
            move.l10n_zw_fdms_document_ids.unlink()

    def test_fiscal_day_close(self):
        move = self._create_invoice()
        move.action_post()
        doc = move.l10n_zw_fdms_document_ids
        doc._send_pending(self.device)
        day = self.device.current_fiscal_day_id
        self.assertEqual(day.state, 'open')
        self.assertTrue(day.action_close())
        self.assertEqual(day.state, 'close_initiated')
        self.assertTrue(day.counters_json)
        counter_types = {c['fiscalCounterType'] for c in day.counters_json}
        self.assertIn('SaleByTax', counter_types)
        self.assertIn('SaleTaxByTax', counter_types)
        self.assertIn('BalanceByMoneyType', counter_types)
        day._poll_close_status()
        self.assertEqual(day.state, 'closed')
        self.assertFalse(self.device.current_fiscal_day_id)
        # Next invoice opens a new day and restarts the per-day chain.
        move2 = self._create_invoice()
        move2.action_post()
        doc2 = move2.l10n_zw_fdms_document_ids
        self.assertEqual(doc2.receipt_counter, 1)
        self.assertFalse(doc2.previous_hash)
        self.assertEqual(doc2.receipt_global_no, 2)
        self.assertEqual(doc2.fiscal_day_id.fiscal_day_no, 2)
