from datetime import datetime, date
from decimal import Decimal

from odoo.tests import BaseCase, tagged

from ..models import fdms_signing


@tagged('standard', 'at_install')
class TestFdmsSigning(BaseCase):
    """Byte-exact tests of the FDMS signature-string builders."""

    def test_to_cents(self):
        self.assertEqual(fdms_signing.to_cents('19.99'), '1999')
        self.assertEqual(fdms_signing.to_cents(19.99), '1999')  # float noise shed via str()
        self.assertEqual(fdms_signing.to_cents(Decimal('115.00')), '11500')
        self.assertEqual(fdms_signing.to_cents(Decimal('-10.50')), '-1050')
        self.assertEqual(fdms_signing.to_cents(0), '0')
        self.assertEqual(fdms_signing.to_cents('0.005'), '1')  # ROUND_HALF_UP

    def test_format_percent(self):
        self.assertEqual(fdms_signing.format_percent('15.5'), '15.50')
        self.assertEqual(fdms_signing.format_percent(0), '0.00')
        self.assertEqual(fdms_signing.format_percent(None), '')
        self.assertEqual(fdms_signing.format_percent(''), '')

    def test_receipt_signature_string(self):
        source = fdms_signing.build_receipt_signature_string(
            device_id=321,
            receipt_type='FiscalInvoice',
            currency='USD',
            receipt_global_no=1,
            receipt_date=datetime(2026, 8, 8, 10, 30, 0),
            receipt_total=Decimal('115.00'),
            receipt_taxes=[{
                'taxID': 515,
                'taxPercent': '15.50',
                'taxAmount': Decimal('15.50'),
                'salesAmountWithTax': Decimal('115.00'),
            }],
        )
        self.assertEqual(
            source,
            '321FISCALINVOICEUSD12026-08-08T10:30:001150015.50155011500')
        _digest, hash_b64 = fdms_signing.sha256_b64(source)
        self.assertEqual(hash_b64, 'q48b/z19qHw4zW153rfhVef7jJV1ox8vftt8K82qadI=')

    def test_receipt_signature_string_chained(self):
        source = fdms_signing.build_receipt_signature_string(
            device_id=321,
            receipt_type='CreditNote',
            currency='USD',
            receipt_global_no=2,
            receipt_date=datetime(2026, 8, 8, 11, 0, 0),
            receipt_total=Decimal('-115.00'),
            receipt_taxes=[{
                'taxID': 515,
                'taxPercent': '15.50',
                'taxAmount': Decimal('-15.50'),
                'salesAmountWithTax': Decimal('-115.00'),
            }],
            previous_receipt_hash_b64='q48b/z19qHw4zW153rfhVef7jJV1ox8vftt8K82qadI=',
        )
        self.assertEqual(
            source,
            '321CREDITNOTEUSD22026-08-08T11:00:00-1150015.50-1550-11500'
            'q48b/z19qHw4zW153rfhVef7jJV1ox8vftt8K82qadI=')

    def test_exempt_tax_empty_percent(self):
        block = fdms_signing.build_receipt_taxes_block([
            {'taxID': 3, 'taxPercent': '', 'taxAmount': 0,
             'salesAmountWithTax': Decimal('50.00')},
            {'taxID': 2, 'taxPercent': '0.00', 'taxAmount': 0,
             'salesAmountWithTax': Decimal('20.00')},
        ])
        # Sorted by taxID: zero-rated (2) first, then exempt (3) with no percent.
        self.assertEqual(block, '0.000200005000')

    def test_verification_code_and_qr(self):
        sig = 'dGVzdC1zaWduYXR1cmUtYnl0ZXMtMDEyMzQ1Njc4OQ=='
        code = fdms_signing.compute_verification_code(sig)
        self.assertEqual(code, 'C4CE5630C6C444E6')
        self.assertEqual(fdms_signing.format_verification_code(code),
                         'C4CE-5630-C6C4-44E6')
        qr = fdms_signing.build_qr_data(
            'https://fdmstest.zimra.co.zw/', 321,
            datetime(2026, 8, 8, 10, 30), 42, sig)
        self.assertEqual(
            qr,
            'https://fdmstest.zimra.co.zw/000000032108082026'
            '0000000042C4CE5630C6C444E6')

    def test_fiscal_day_signature_string(self):
        counters = [
            {'fiscalCounterType': 'SaleTaxByTax', 'fiscalCounterCurrency': 'USD',
             'fiscalCounterTaxID': 515, 'fiscalCounterTaxPercent': '15.50',
             'fiscalCounterValue': Decimal('15.50')},
            {'fiscalCounterType': 'SaleByTax', 'fiscalCounterCurrency': 'USD',
             'fiscalCounterTaxID': 515, 'fiscalCounterTaxPercent': '15.50',
             'fiscalCounterValue': Decimal('115.00')},
            {'fiscalCounterType': 'BalanceByMoneyType', 'fiscalCounterCurrency': 'USD',
             'fiscalCounterMoneyType': 'Cash', 'fiscalCounterValue': Decimal('115.00')},
            # zero counters must be skipped
            {'fiscalCounterType': 'CreditNoteByTax', 'fiscalCounterCurrency': 'USD',
             'fiscalCounterTaxID': 2, 'fiscalCounterTaxPercent': '0.00',
             'fiscalCounterValue': Decimal('0')},
        ]
        source = fdms_signing.build_fiscal_day_signature_string(
            321, 7, date(2026, 8, 8), counters)
        self.assertEqual(
            source,
            '3217' '2026-08-08'
            'BALANCEBYMONEYTYPE' 'USD' 'CASH' '11500'
            'SALEBYTAX' 'USD' '15.50' '11500'
            'SALETAXBYTAX' 'USD' '15.50' '1550')
