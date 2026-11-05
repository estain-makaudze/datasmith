# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class FuelNozzle(models.Model):
    _name = 'fuel.nozzle'
    _description = 'Pump Nozzle'
    _order = 'pump_id, sequence, name'

    name = fields.Char(string='Nozzle', required=True, help='Nozzle label on the pump, e.g. A or 1.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    pump_id = fields.Many2one('fuel.pump', string='Pump', required=True, ondelete='cascade')
    site_id = fields.Many2one(related='pump_id.site_id', store=True, string='Site')
    company_id = fields.Many2one(related='pump_id.company_id', store=True)
    tank_id = fields.Many2one(
        'fuel.tank', string='Tank', required=True, ondelete='restrict',
        help='The tank this nozzle draws from. Sales here reduce that tank.')
    product_id = fields.Many2one(related='tank_id.product_id', store=True, string='Product')
    current_totaliser = fields.Float(
        string='Current Totaliser (l)', digits=(16, 2),
        help='Lifetime litre counter as last confirmed on a shift. Never resets. '
             'Set it once when the nozzle is first registered.')

    _name_pump_uniq = models.Constraint(
        'UNIQUE(name, pump_id)',
        'Another nozzle on this pump already has that name.',
    )
    _totaliser_positive = models.Constraint(
        'CHECK(current_totaliser >= 0)',
        'A totaliser reading cannot be negative.',
    )

    @api.depends('name', 'pump_id')
    def _compute_display_name(self):
        for nozzle in self:
            nozzle.display_name = '%s%s' % (nozzle.pump_id.display_name and
                                            nozzle.pump_id.display_name + ' ' or '', nozzle.name)

    @api.constrains('tank_id', 'pump_id')
    def _check_tank_site(self):
        """A nozzle cannot draw from a tank buried at another station."""
        for nozzle in self:
            if nozzle.tank_id.site_id != nozzle.pump_id.site_id:
                raise ValidationError(_(
                    'Nozzle %(nozzle)s is on a pump at %(pump_site)s but draws from a '
                    'tank at %(tank_site)s. Pick a tank at the same site.',
                    nozzle=nozzle.name,
                    pump_site=nozzle.pump_id.site_id.display_name,
                    tank_site=nozzle.tank_id.site_id.display_name))

    @api.onchange('pump_id')
    def _onchange_pump_id(self):
        """Offer only tanks at this pump's site."""
        if self.pump_id and self.tank_id.site_id != self.pump_id.site_id:
            self.tank_id = False
        return {'domain': {'tank_id': [('site_id', '=', self.pump_id.site_id.id)]}}
