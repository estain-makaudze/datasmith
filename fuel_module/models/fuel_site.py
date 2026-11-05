# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FuelSite(models.Model):
    _name = 'fuel.site'
    _description = 'Fuel Station Site'
    _order = 'name'

    name = fields.Char(string='Site', required=True)
    code = fields.Char(string='Code', required=True,
                       help='Short code used on shift and delivery references, e.g. MSA.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    manager_id = fields.Many2one('res.users', string='Station Manager')
    street = fields.Char(string='Address')
    city = fields.Char(string='City')
    phone = fields.Char(string='Phone')
    tolerance_percent = fields.Float(
        string='Wet Stock Tolerance (%)', default=lambda self: self._default_tolerance(),
        help='Variance allowed between book stock and the dip, as a percentage of '
             'throughput, before a tank is flagged on the shift.')

    tank_ids = fields.One2many('fuel.tank', 'site_id', string='Tanks')
    pump_ids = fields.One2many('fuel.pump', 'site_id', string='Pumps')
    attendant_ids = fields.One2many('fuel.attendant', 'site_id', string='Attendants')

    tank_count = fields.Integer(compute='_compute_counts')
    pump_count = fields.Integer(compute='_compute_counts')
    nozzle_count = fields.Integer(compute='_compute_counts')
    attendant_count = fields.Integer(compute='_compute_counts')

    _code_company_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Another site in this company already uses that code.',
    )

    @api.model
    def _default_tolerance(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'fuel_module.default_tolerance')
        try:
            return float(param) if param else 0.5
        except (TypeError, ValueError):
            return 0.5

    @api.depends('tank_ids', 'pump_ids', 'pump_ids.nozzle_ids', 'attendant_ids')
    def _compute_counts(self):
        for site in self:
            site.tank_count = len(site.tank_ids)
            site.pump_count = len(site.pump_ids)
            site.nozzle_count = len(site.pump_ids.nozzle_ids)
            site.attendant_count = len(site.attendant_ids)

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for site in self:
            site.display_name = '%s (%s)' % (site.name, site.code) if site.code else site.name

    def _action_related(self, model, xml_id, name, domain, context=None):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': model,
            'view_mode': 'list,form',
            'domain': domain,
            'context': dict(context or {}, default_site_id=self.id),
        }

    def action_view_tanks(self):
        return self._action_related(
            'fuel.tank', 'action_fuel_tank', 'Tanks', [('site_id', '=', self.id)])

    def action_view_pumps(self):
        return self._action_related(
            'fuel.pump', 'action_fuel_pump', 'Pumps', [('site_id', '=', self.id)])

    def action_view_nozzles(self):
        return self._action_related(
            'fuel.nozzle', 'action_fuel_nozzle', 'Nozzles', [('site_id', '=', self.id)])

    def action_view_attendants(self):
        return self._action_related(
            'fuel.attendant', 'action_fuel_attendant', 'Attendants',
            [('site_id', '=', self.id)])
