# -*- coding: utf-8 -*-
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestTankChart(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env['product.product'].create({
            'name': 'Petrol Blend E5',
            'is_fuel_grade': True,
        })
        cls.site = cls.env['fuel.site'].create({
            'name': 'Msasa Service Station',
            'code': 'MSA',
        })
        cls.tank = cls.env['fuel.tank'].create({
            'name': 'Tank 1',
            'site_id': cls.site.id,
            'product_id': cls.product.id,
            'capacity_litres': 40000.0,
            'dead_stock_litres': 500.0,
            'safe_fill_percent': 95.0,
            # A deliberately coarse chart, as a calibration certificate gives it.
            'chart_line_ids': [
                (0, 0, {'dip_mm': 0.0, 'litres': 0.0}),
                (0, 0, {'dip_mm': 500.0, 'litres': 8000.0}),
                (0, 0, {'dip_mm': 1000.0, 'litres': 20000.0}),
                (0, 0, {'dip_mm': 1500.0, 'litres': 32000.0}),
                (0, 0, {'dip_mm': 2000.0, 'litres': 40000.0}),
            ],
        })

    def test_exact_chart_row(self):
        """A dip that lands on a chart row returns that row."""
        self.assertAlmostEqual(self.tank.dip_to_litres(1000.0), 20000.0, places=2)

    def test_interpolates_between_rows(self):
        """Halfway between 1000 mm and 1500 mm is halfway between 20,000 and 32,000."""
        self.assertAlmostEqual(self.tank.dip_to_litres(1250.0), 26000.0, places=2)
        # A quarter of the way up the same band.
        self.assertAlmostEqual(self.tank.dip_to_litres(1125.0), 23000.0, places=2)

    def test_empty_and_negative(self):
        self.assertEqual(self.tank.dip_to_litres(0.0), 0.0)
        self.assertEqual(self.tank.dip_to_litres(-50.0), 0.0)

    def test_above_last_row_clamps(self):
        """Never extrapolate past the certificate; the tank cannot hold more."""
        self.assertAlmostEqual(self.tank.dip_to_litres(2500.0), 40000.0, places=2)

    def test_chart_required(self):
        bare = self.env['fuel.tank'].create({
            'name': 'Tank 9',
            'site_id': self.site.id,
            'product_id': self.product.id,
            'capacity_litres': 10000.0,
        })
        with self.assertRaises(UserError):
            bare.dip_to_litres(500.0)

    def test_chart_must_rise(self):
        with self.assertRaises(ValidationError):
            self.tank.write({'chart_line_ids': [
                (0, 0, {'dip_mm': 1800.0, 'litres': 25000.0}),
            ]})

    def test_duplicate_dip_rejected(self):
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.env['fuel.tank.chart.line'].create({
                    'tank_id': self.tank.id, 'dip_mm': 1000.0, 'litres': 20100.0})

    def test_dead_stock_below_capacity(self):
        with self.assertRaises(ValidationError):
            self.tank.write({'dead_stock_litres': 50000.0})

    def test_nozzle_must_match_site(self):
        other_site = self.env['fuel.site'].create({'name': 'Chitungwiza', 'code': 'CHI'})
        pump = self.env['fuel.pump'].create({'name': 'Pump 1', 'site_id': other_site.id})
        with self.assertRaises(ValidationError):
            self.env['fuel.nozzle'].create({
                'name': 'A', 'pump_id': pump.id, 'tank_id': self.tank.id})

    def test_attendant_gets_partner(self):
        attendant = self.env['fuel.attendant'].create({
            'name': 'Tendai Moyo', 'site_id': self.site.id, 'code': 'A01'})
        self.assertTrue(attendant.partner_id, 'An attendant must carry a partner for shortages.')
        attendant.write({'name': 'Tendai M Moyo'})
        self.assertEqual(attendant.partner_id.name, 'Tendai M Moyo')

    def test_dip_test_wizard(self):
        wizard = self.env['fuel.dip.test'].create({
            'tank_id': self.tank.id, 'dip_mm': 1250.0})
        self.assertAlmostEqual(wizard.litres, 26000.0, places=2)
        # Safe fill is 95% of 40,000 = 38,000; ullage is what is left to that.
        self.assertAlmostEqual(wizard.ullage_litres, 12000.0, places=2)
