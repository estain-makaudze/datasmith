# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Datetime
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestFuelPrice(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.petrol = cls.env['product.product'].create({
            'name': 'Petrol', 'is_fuel_grade': True})
        cls.diesel = cls.env['product.product'].create({
            'name': 'Diesel', 'is_fuel_grade': True})
        cls.msasa = cls.env['fuel.site'].create({'name': 'Msasa', 'code': 'MSA'})
        cls.chitown = cls.env['fuel.site'].create({'name': 'Chitungwiza', 'code': 'CHI'})
        cls.Price = cls.env['fuel.price']
        # Monday, then a change on Wednesday at 16:00.
        cls.monday = Datetime.to_datetime('2026-09-07 06:00:00')
        cls.wednesday = Datetime.to_datetime('2026-09-09 16:00:00')
        cls.p_monday = cls.Price.create({
            'product_id': cls.petrol.id, 'price': 1.55, 'valid_from': cls.monday})
        cls.p_wednesday = cls.Price.create({
            'product_id': cls.petrol.id, 'price': 1.58, 'valid_from': cls.wednesday})

    def test_price_either_side_of_a_change(self):
        before = self.Price._get_price(
            self.msasa, self.petrol, Datetime.to_datetime('2026-09-09 15:59:00'))
        after = self.Price._get_price(
            self.msasa, self.petrol, Datetime.to_datetime('2026-09-09 16:00:01'))
        self.assertEqual(before, self.p_monday)
        self.assertEqual(after, self.p_wednesday)

    def test_exactly_at_the_change(self):
        """Valid from 16:00 means 16:00 itself is already the new price."""
        at = self.Price._get_price(self.msasa, self.petrol, self.wednesday)
        self.assertEqual(at, self.p_wednesday)

    def test_before_any_price_is_empty(self):
        self.assertFalse(self.Price._get_price(
            self.msasa, self.petrol, Datetime.to_datetime('2026-09-01 08:00:00')))

    def test_unpriced_product_raises_naming_it(self):
        with self.assertRaises(UserError):
            self.Price._get_price_value(self.msasa, self.diesel, self.wednesday)

    def test_site_override_beats_all_sites(self):
        override = self.Price.create({
            'product_id': self.petrol.id, 'site_id': self.msasa.id,
            'price': 1.60, 'valid_from': self.monday})
        when = Datetime.to_datetime('2026-09-10 08:00:00')
        self.assertEqual(self.Price._get_price(self.msasa, self.petrol, when), override,
                         'A site price must win even when the all-sites price is newer.')
        self.assertEqual(self.Price._get_price(self.chitown, self.petrol, when),
                         self.p_wednesday, 'Other sites keep the all-sites price.')

    def test_duplicate_instant_rejected(self):
        with self.assertRaises(ValidationError):
            self.Price.create({
                'product_id': self.petrol.id, 'price': 1.57,
                'valid_from': self.wednesday})

    def test_periods_split_a_shift_across_a_change(self):
        """A 14:00-22:00 shift on Wednesday sells at two prices."""
        start = Datetime.to_datetime('2026-09-09 14:00:00')
        end = Datetime.to_datetime('2026-09-09 22:00:00')
        periods = self.Price._get_price_periods(self.msasa, self.petrol, start, end)
        self.assertEqual(len(periods), 2)
        self.assertEqual(periods[0], (start, self.wednesday, self.p_monday))
        self.assertEqual(periods[1], (self.wednesday, end, self.p_wednesday))

    def test_periods_single_when_no_change(self):
        start = Datetime.to_datetime('2026-09-08 06:00:00')
        end = Datetime.to_datetime('2026-09-08 14:00:00')
        periods = self.Price._get_price_periods(self.msasa, self.petrol, start, end)
        self.assertEqual(len(periods), 1)
        self.assertEqual(periods[0][2], self.p_monday)

    def test_periods_empty_before_first_price(self):
        start = Datetime.to_datetime('2026-09-01 06:00:00')
        end = Datetime.to_datetime('2026-09-01 14:00:00')
        self.assertFalse(
            self.Price._get_price_periods(self.msasa, self.petrol, start, end))

    def test_price_status(self):
        self.assertEqual(self.p_monday.price_status, 'superseded')
        self.assertEqual(self.p_wednesday.price_status, 'current')
        future = self.Price.create({
            'product_id': self.petrol.id, 'price': 1.61,
            'valid_from': Datetime.to_datetime('2099-01-01 06:00:00')})
        self.assertEqual(future.price_status, 'scheduled')

    def test_site_current_prices_tab(self):
        tank = self.env['fuel.tank'].create({
            'name': 'Tank 1', 'site_id': self.msasa.id, 'product_id': self.petrol.id,
            'capacity_litres': 40000.0})
        self.assertTrue(tank)
        self.msasa.invalidate_recordset()
        self.assertIn(self.p_wednesday, self.msasa.current_price_ids)
