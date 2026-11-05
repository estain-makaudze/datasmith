# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.fields import Datetime
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestShiftPosting(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.petrol = cls.env['product.product'].create({
            'name': 'Petrol P', 'is_fuel_grade': True})
        cls.site = cls.env['fuel.site'].create({
            'name': 'Msasa P', 'code': 'MSP', 'tolerance_percent': 0.5})
        cls.tank = cls.env['fuel.tank'].create({
            'name': 'Tank 1', 'site_id': cls.site.id, 'product_id': cls.petrol.id,
            'capacity_litres': 40000.0, 'average_cost': 1.20,
            'chart_line_ids': [
                (0, 0, {'dip_mm': 0.0, 'litres': 0.0}),
                (0, 0, {'dip_mm': 1000.0, 'litres': 20000.0}),
                (0, 0, {'dip_mm': 2000.0, 'litres': 40000.0}),
            ]})
        cls.pump = cls.env['fuel.pump'].create({'name': 'P1', 'site_id': cls.site.id})
        cls.nozzle = cls.env['fuel.nozzle'].create({
            'name': 'A', 'pump_id': cls.pump.id, 'tank_id': cls.tank.id,
            'current_totaliser': 0.0})
        cls.tendai = cls.env['fuel.attendant'].create({
            'name': 'Tendai P', 'site_id': cls.site.id, 'is_supervisor': True})
        cls.env['fuel.price'].create({
            'product_id': cls.petrol.id, 'price': 1.50,
            'valid_from': Datetime.to_datetime('2026-09-01 00:00:00')})

        cls.cash = cls.env.ref('fuel_module.payment_method_cash_usd').copy({
            'name': 'Cash USD T', 'code': 'cash_usd_t'})

        def account(code, name, account_type):
            return cls.env['account.account'].create({
                'code': code, 'name': name, 'account_type': account_type})
        cls.acc_cash = account('F1001', 'Forecourt cash clearing', 'asset_current')
        cls.acc_short = account('F1002', 'Attendant shortages', 'asset_receivable')
        cls.acc_stock = account('F1003', 'Fuel stock', 'asset_current')
        cls.acc_cogs = account('F5001', 'Fuel cost of sales', 'expense')
        cls.acc_loss = account('F5002', 'Wet stock loss', 'expense')
        cls.acc_sales = account('F4001', 'Fuel sales', 'income')
        cls.cash.account_id = cls.acc_cash
        cls.journal = cls.env['account.journal'].create({
            'name': 'Forecourt', 'code': 'FCT', 'type': 'general'})
        cls.tax = cls.env['account.tax'].search(
            [('type_tax_use', '=', 'sale'), ('amount', '=', 15.0)], limit=1)

        params = cls.env['ir.config_parameter'].sudo()
        params.set_param('fuel_module.journal_id', cls.journal.id)
        params.set_param('fuel_module.sales_account_id', cls.acc_sales.id)
        params.set_param('fuel_module.shortage_account_id', cls.acc_short.id)
        params.set_param('fuel_module.stock_account_id', cls.acc_stock.id)
        params.set_param('fuel_module.cogs_account_id', cls.acc_cogs.id)
        params.set_param('fuel_module.stock_loss_account_id', cls.acc_loss.id)
        params.set_param('fuel_module.tax_id', cls.tax.id)
        params.set_param('fuel_module.price_tax_included', 'True')

    def _posted_shift(self, declared=1500.0, closing_dip=850.0, label='1'):
        """1,000 litres at $1.50 = $1,500 expected. Tank opened at 20,000 l."""
        shift = self.env['fuel.shift'].create({
            'site_id': self.site.id, 'date': '2026-09-20', 'shift_label': label,
            'start_datetime': Datetime.to_datetime('2026-09-20 06:00:00'),
            'end_datetime': Datetime.to_datetime('2026-09-20 14:00:00'),
            'supervisor_id': self.tendai.id,
            'nozzle_line_ids': [(0, 0, {
                'nozzle_id': self.nozzle.id, 'attendant_id': self.tendai.id,
                'opening_totaliser': self.nozzle.current_totaliser})],
            'tank_line_ids': [(0, 0, {
                'tank_id': self.tank.id, 'opening_dip_mm': 1000.0})],
        })
        shift.nozzle_line_ids[0].closing_totaliser = \
            shift.nozzle_line_ids[0].opening_totaliser + 1000.0
        shift.tank_line_ids[0].closing_dip_mm = closing_dip
        if declared:
            self.env['fuel.shift.tender.line'].create({
                'shift_id': shift.id, 'attendant_id': self.tendai.id,
                'method_id': self.cash.id, 'currency_id': shift.currency_id.id,
                'amount': declared})
        shift.action_open()
        shift.action_close()
        shift.action_confirm()
        return shift

    def test_entry_balances_and_splits_vat(self):
        shift = self._posted_shift()
        shift.action_post()
        move = shift.move_id
        self.assertTrue(move, 'A posted shift must carry its entry.')
        self.assertEqual(move.state, 'posted')
        self.assertEqual(shift.state, 'posted')
        self.assertAlmostEqual(
            sum(move.line_ids.mapped('debit')), sum(move.line_ids.mapped('credit')),
            places=2)
        sales = move.line_ids.filtered(lambda l: l.account_id == self.acc_sales)
        vat = move.line_ids.filtered(lambda l: l.tax_repartition_line_id)
        # $1,500 gross at 15% inclusive: 1,304.35 net and 195.65 VAT.
        self.assertAlmostEqual(sales.credit, 1304.35, places=2)
        self.assertAlmostEqual(vat.credit, 195.65, places=2)
        self.assertAlmostEqual(sales.credit + vat.credit, 1500.0, places=2)

    def test_vat_reaches_the_tax_report(self):
        shift = self._posted_shift()
        shift.action_post()
        sales = shift.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_sales)
        self.assertIn(self.tax, sales.tax_ids,
                      'The sales line must carry the tax, or VAT never reaches the return.')

    def test_cash_and_cost_lines(self):
        shift = self._posted_shift()
        shift.action_post()
        lines = shift.move_id.line_ids
        cash = lines.filtered(lambda l: l.account_id == self.acc_cash)
        cogs = lines.filtered(lambda l: l.account_id == self.acc_cogs)
        self.assertAlmostEqual(cash.debit, 1500.0, places=2)
        self.assertAlmostEqual(cogs.debit, 1200.0, places=2, msg='1,000 l at $1.20.')

    def test_shortage_lands_on_the_attendant_partner(self):
        shift = self._posted_shift(declared=1462.0)
        shift.action_post()
        short = shift.move_id.line_ids.filtered(
            lambda l: l.account_id == self.acc_short)
        self.assertAlmostEqual(short.debit, 38.0, places=2)
        self.assertEqual(short.partner_id, self.tendai.partner_id)

    def test_wet_stock_loss_is_valued_at_cost(self):
        """Book says 19,000 l; the dip says 17,000. 2,000 l gone at $1.20."""
        shift = self._posted_shift(closing_dip=850.0)
        self.assertAlmostEqual(shift.tank_line_ids[0].variance_litres, -2000.0, places=2)
        shift.action_post()
        loss = shift.move_id.line_ids.filtered(lambda l: l.account_id == self.acc_loss)
        self.assertAlmostEqual(loss.debit, 2400.0, places=2)

    def test_cannot_post_twice(self):
        shift = self._posted_shift()
        shift.action_post()
        with self.assertRaises(UserError):
            shift.action_post()

    def test_cannot_post_before_confirming(self):
        shift = self.env['fuel.shift'].create({
            'site_id': self.site.id, 'date': '2026-09-21', 'shift_label': '2',
            'start_datetime': Datetime.to_datetime('2026-09-21 06:00:00')})
        with self.assertRaises(UserError):
            shift.action_post()

    def test_posted_shift_cannot_be_reset_or_deleted(self):
        shift = self._posted_shift()
        shift.action_post()
        with self.assertRaises(UserError):
            shift.action_reset_to_draft()
        with self.assertRaises(UserError):
            shift.unlink()

    def test_missing_clearing_account_names_the_method(self):
        self.cash.account_id = False
        shift = self._posted_shift()
        with self.assertRaises(UserError):
            shift.action_post()

    def test_missing_journal_names_the_setting(self):
        self.env['ir.config_parameter'].sudo().set_param('fuel_module.journal_id', '')
        shift = self._posted_shift()
        with self.assertRaises(UserError):
            shift.action_post()
