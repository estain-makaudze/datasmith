# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FuelDipTest(models.TransientModel):
    _name = 'fuel.dip.test'
    _description = 'Test a Dip Against the Strapping Chart'

    tank_id = fields.Many2one('fuel.tank', string='Tank', required=True)
    dip_mm = fields.Float(string='Dip (mm)', required=True, digits=(16, 1))
    litres = fields.Float(string='Litres', compute='_compute_litres', digits=(16, 2))
    ullage_litres = fields.Float(
        string='Ullage (l)', compute='_compute_litres', digits=(16, 2),
        help='Empty space left, against the tank\'s safe fill level.')
    chart_line_count = fields.Integer(related='tank_id.chart_line_count')

    @api.depends('tank_id', 'dip_mm')
    def _compute_litres(self):
        for wizard in self:
            if not wizard.tank_id or not wizard.tank_id.chart_line_ids:
                wizard.litres = 0.0
                wizard.ullage_litres = 0.0
                continue
            litres = wizard.tank_id.dip_to_litres(wizard.dip_mm)
            safe_fill = (wizard.tank_id.capacity_litres *
                         (wizard.tank_id.safe_fill_percent or 100.0) / 100.0)
            wizard.litres = litres
            wizard.ullage_litres = max(safe_fill - litres, 0.0)
