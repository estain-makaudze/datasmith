# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Datetime
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFuelShift(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.petrol = cls.env['product.product'].create({
            'name': 'Petrol', 'is_fuel_grade': True})
        cls.site = cls.env['fuel.site'].create({
            'name': 'Msasa', 'code': 'MSA', 'tolerance_percent': 0.5})
        cls.tank = cls.env['fuel.tank'].create({
            'name': 'Tank 1', 'site_id': cls.site.id, 'product_id': cls.petrol.id,
            'capacity_litres': 40000.0,
            'chart_line_ids': [
                (0, 0, {'dip_mm': 0.0, 'litres': 0.0}),
                (0, 0, {'dip_mm': 1000.0, 'litres': 20000.0}),
                (0, 0, {'dip_mm': 2000.0, 'litres': 40000.0}),
            ]})
        cls.pump = cls.env['fuel.pump'].create({
            'name': 'Pump 1', 'site_id': cls.site.id})
        cls.nozzle_a = cls.env['fuel.nozzle'].create({
            'name': 'A', 'pump_id': cls.pump.id, 'tank_id': cls.tank.id,
            'current_totaliser': 100000.0})
        cls.nozzle_b = cls.env['fuel.nozzle'].create({
            'name': 'B', 'pump_id': cls.pump.id, 'tank_id': cls.tank.id,
            'current_totaliser': 50000.0})
        cls.tendai = cls.env['fuel.attendant'].create({
            'name': 'Tendai', 'site_id': cls.site.id, 'code': 'A01'})
        cls.rudo = cls.env['fuel.attendant'].create({
            'name': 'Rudo', 'site_id': cls.site.id, 'code': 'A02',
            'is_supervisor': True})
        cls.env['fuel.price'].create({
            'product_id': cls.petrol.id, 'price': 1.50,
            'valid_from': Datetime.to_datetime('2026-09-01 00:00:00')})
        cls.cash = cls.env.ref('fuel_module.payment_method_cash_usd')
        cls.start = Datetime.to_datetime('2026-09-10 06:00:00')
        cls.end = Datetime.to_datetime('2026-09-10 14:00:00')

    def _new_shift(self, opening_dip=1000.0):
        """A shift with 1,000 litres sold off nozzle A and a tank opened at 20,000 l."""
        shift = self.env['fuel.shift'].create({
            'site_id': self.site.id,
            'date': '2026-09-10',
            'shift_label': '1',
            'start_datetime': self.start,
            'end_datetime': self.end,
            'supervisor_id': self.rudo.id,
            'nozzle_line_ids': [
                (0, 0, {'nozzle_id': self.nozzle_a.id, 'attendant_id': self.tendai.id,
                        'opening_totaliser': 100000.0}),
                (0, 0, {'nozzle_id': self.nozzle_b.id, 'attendant_id': self.tendai.id,
                        'opening_totaliser': 50000.0}),
            ],
            'tank_line_ids': [
                (0, 0, {'tank_id': self.tank.id, 'opening_dip_mm': opening_dip}),
            ],
        })
        return shift

    def test_sequence_and_initial_state(self):
        shift = self._new_shift()
        self.assertNotEqual(shift.name, 'New')
        self.assertTrue(shift.name.startswith('SHF'))
        self.assertEqual(shift.state, 'draft')

    def test_litres_net_of_test_litres(self):
        """Test litres cross the meter but go back in the tank, so they are not sold."""
        shift = self._new_shift()
        line = shift.nozzle_line_ids[0]
        line.write({'closing_totaliser': 101020.0, 'test_litres': 20.0})
        self.assertAlmostEqual(line.litres_sold, 1000.0, places=2)
        self.assertAlmostEqual(line.amount_expected, 1500.0, places=2)

    def test_closing_below_opening_rejected(self):
        shift = self._new_shift()
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                shift.nozzle_line_ids[0].closing_totaliser = 99999.0

    def test_test_litres_cannot_exceed_throughput(self):
        shift = self._new_shift()
        with self.assertRaises(ValidationError):
            shift.nozzle_line_ids[0].write({
                'closing_totaliser': 100010.0, 'test_litres': 50.0})

    def test_wet_stock_variance_and_tolerance(self):
        """1,000 l sold, dip says 18,900 against a book of 19,000: 100 l missing."""
        shift = self._new_shift()
        shift.nozzle_line_ids[0].closing_totaliser = 101000.0
        tank_line = shift.tank_line_ids[0]
        tank_line.closing_dip_mm = 945.0   # 18,900 litres on this chart
        self.assertAlmostEqual(tank_line.opening_litres, 20000.0, places=2)
        self.assertAlmostEqual(tank_line.sold_litres, 1000.0, places=2)
        self.assertAlmostEqual(tank_line.book_closing_litres, 19000.0, places=2)
        self.assertAlmostEqual(tank_line.closing_litres, 18900.0, places=2)
        self.assertAlmostEqual(tank_line.variance_litres, -100.0, places=2)
        self.assertAlmostEqual(tank_line.variance_percent, -10.0, places=2)
        self.assertTrue(tank_line.over_tolerance, '10% is far beyond a 0.5% tolerance.')

    def test_within_tolerance_is_not_flagged(self):
        shift = self._new_shift()
        shift.nozzle_line_ids[0].closing_totaliser = 101000.0
        tank_line = shift.tank_line_ids[0]
        tank_line.closing_dip_mm = 949.85   # 19,997 litres, 3 l short of book
        self.assertFalse(tank_line.over_tolerance)

    def test_delivery_during_shift_raises_book_stock(self):
        shift = self._new_shift()
        shift.nozzle_line_ids[0].closing_totaliser = 101000.0
        tank_line = shift.tank_line_ids[0]
        tank_line.write({'delivered_litres': 5000.0, 'closing_dip_mm': 1200.0})
        self.assertAlmostEqual(tank_line.book_closing_litres, 24000.0, places=2)
        self.assertAlmostEqual(tank_line.closing_litres, 24000.0, places=2)
        self.assertAlmostEqual(tank_line.variance_litres, 0.0, places=2)

    def test_no_closing_dip_means_no_wet_reconciliation(self):
        """Sites that dip once a day still close shifts; cash is unaffected."""
        shift = self._new_shift()
        shift.nozzle_line_ids[0].closing_totaliser = 101000.0
        shift.nozzle_line_ids[1].closing_totaliser = 50000.0
        shift.action_open()
        shift.action_close()
        self.assertTrue(shift.dips_missing)
        self.assertEqual(shift.total_wet_variance, 0.0)
        self.assertFalse(shift.has_tolerance_breach)

    def test_tender_in_another_currency_uses_the_rate_given(self):
        shift = self._new_shift()
        zig = self.env['res.currency'].create({'name': 'ZiGT', 'symbol': 'ZiGT'})
        line = self.env['fuel.shift.tender.line'].create({
            'shift_id': shift.id, 'attendant_id': self.tendai.id,
            'method_id': self.cash.id, 'currency_id': zig.id,
            'amount': 1300.0, 'rate': 0.04})
        self.assertAlmostEqual(line.company_amount, 52.0, places=2)

    def test_reference_required_for_mobile_money(self):
        shift = self._new_shift()
        ecocash = self.env.ref('fuel_module.payment_method_ecocash')
        with self.assertRaises(ValidationError):
            self.env['fuel.shift.tender.line'].create({
                'shift_id': shift.id, 'method_id': ecocash.id,
                'currency_id': shift.currency_id.id, 'amount': 40.0})

    def test_shortage_lands_on_one_attendant(self):
        shift = self._new_shift()
        shift.nozzle_line_ids[0].closing_totaliser = 101000.0   # 1,000 l = $1,500
        shift.nozzle_line_ids[1].closing_totaliser = 50000.0
        self.env['fuel.shift.tender.line'].create({
            'shift_id': shift.id, 'attendant_id': self.tendai.id,
            'method_id': self.cash.id, 'currency_id': shift.currency_id.id,
            'amount': 1462.0})
        shift.action_open()
        shift.action_close()
        self.assertAlmostEqual(shift.total_expected, 1500.0, places=2)
        self.assertAlmostEqual(shift.total_declared, 1462.0, places=2)
        self.assertAlmostEqual(shift.total_shortage, 38.0, places=2)
        line = shift.attendant_line_ids.filtered(lambda l: l.attendant_id == self.tendai)
        self.assertAlmostEqual(line.amount_shortage, 38.0, places=2)
        self.assertEqual(line.partner_id, self.tendai.partner_id)

    def test_cannot_close_without_every_closing_reading(self):
        shift = self._new_shift()
        shift.nozzle_line_ids[0].closing_totaliser = 101000.0
        shift.action_open()
        with self.assertRaises(UserError):
            shift.action_close()

    def test_confirm_moves_the_nozzle_counters_on(self):
        shift = self._new_shift()
        shift.nozzle_line_ids[0].closing_totaliser = 101000.0
        shift.nozzle_line_ids[1].closing_totaliser = 50500.0
        shift.action_open()
        shift.action_close()
        shift.action_confirm()
        self.assertEqual(shift.state, 'confirmed')
        self.assertAlmostEqual(self.nozzle_a.current_totaliser, 101000.0, places=2)
        self.assertAlmostEqual(self.nozzle_b.current_totaliser, 50500.0, places=2)

    def test_second_shift_opens_where_the_first_closed(self):
        first = self._new_shift()
        first.nozzle_line_ids[0].closing_totaliser = 101000.0
        first.nozzle_line_ids[1].closing_totaliser = 50500.0
        first.tank_line_ids[0].closing_dip_mm = 950.0
        first.action_open()
        first.action_close()
        first.action_confirm()
        second = self.env['fuel.shift'].new({
            'site_id': self.site.id, 'date': '2026-09-10', 'shift_label': '2',
            'start_datetime': Datetime.to_datetime('2026-09-10 14:00:00')})
        second._onchange_site_id()
        openings = {l.nozzle_id: l.opening_totaliser for l in second.nozzle_line_ids}
        self.assertAlmostEqual(openings[self.nozzle_a], 101000.0, places=2)
        self.assertAlmostEqual(openings[self.nozzle_b], 50500.0, places=2)
        self.assertAlmostEqual(second.tank_line_ids[0].opening_dip_mm, 950.0, places=1)

    def test_gap_in_opening_reading_is_logged(self):
        """Opening somewhere other than last night's close is the classic cover-up."""
        shift = self._new_shift()
        shift.nozzle_line_ids[0].opening_totaliser = 100500.0
        shift.action_open()
        body = ' '.join(shift.message_ids.mapped('body'))
        self.assertIn('unaccounted', body)

    def test_duplicate_shift_slot_rejected(self):
        self._new_shift()
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['fuel.shift'].create({
                    'site_id': self.site.id, 'date': '2026-09-10', 'shift_label': '1',
                    'start_datetime': self.start})

    def test_supervisor_must_belong_to_the_site(self):
        other = self.env['fuel.site'].create({'name': 'Chitungwiza', 'code': 'CHI'})
        stranger = self.env['fuel.attendant'].create({
            'name': 'Farai', 'site_id': other.id, 'is_supervisor': True})
        with self.assertRaises(ValidationError):
            self.env['fuel.shift'].create({
                'site_id': self.site.id, 'date': '2026-09-11', 'shift_label': '1',
                'start_datetime': self.start, 'supervisor_id': stranger.id})

    def test_price_change_mid_shift_warns(self):
        self.env['fuel.price'].create({
            'product_id': self.petrol.id, 'price': 1.58,
            'valid_from': Datetime.to_datetime('2026-09-10 10:00:00')})
        shift = self._new_shift()
        shift.nozzle_line_ids[0].closing_totaliser = 101000.0
        shift.invalidate_recordset()
        self.assertIn('changed during this shift', shift.price_change_warning or '')
