# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FuelPump(models.Model):
    _name = 'fuel.pump'
    _description = 'Forecourt Pump'
    _order = 'site_id, sequence, name'

    name = fields.Char(string='Pump', required=True, help='As numbered on the forecourt, e.g. Pump 3.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    site_id = fields.Many2one('fuel.site', string='Site', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='site_id.company_id', store=True)
    nozzle_ids = fields.One2many('fuel.nozzle', 'pump_id', string='Nozzles')
    nozzle_count = fields.Integer(compute='_compute_nozzle_count')
    note = fields.Char(string='Note', help='Make and model, or anything the calibrator should know.')

    _name_site_uniq = models.Constraint(
        'UNIQUE(name, site_id)',
        'Another pump at this site already has that name.',
    )

    @api.depends('nozzle_ids')
    def _compute_nozzle_count(self):
        for pump in self:
            pump.nozzle_count = len(pump.nozzle_ids)

    @api.depends('name', 'site_id')
    def _compute_display_name(self):
        for pump in self:
            site = pump.site_id.code or pump.site_id.name
            pump.display_name = '%s / %s' % (site, pump.name) if site else pump.name
