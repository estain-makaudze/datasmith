# -*- coding: utf-8 -*-
from odoo import api, fields, models


class TransportRoute(models.Model):
    _name = 'transport.route'
    _description = 'Transport Route'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'route_name'
    _rec_names_search = ['name', 'route_name', 'origin', 'destination']

    name = fields.Char(string='Route Number', required=True, copy=False,
                       readonly=True, default='New')
    route_name = fields.Char(string='Route', required=True, tracking=True,
                             help='Display name of the route, e.g. "Mbare – CBD".')
    origin = fields.Char(string='Origin', tracking=True)
    destination = fields.Char(string='Destination', tracking=True)
    distance_km = fields.Float(string='Distance (km)', digits=(10, 1))
    standard_fare_usd = fields.Float(string='Standard Fare (USD)', digits=(10, 2),
                                     help='Usual fare per passenger in USD.')
    standard_fare_zwg = fields.Float(string='Standard Fare (ZWG)', digits=(10, 2),
                                     help='Usual fare per passenger in ZWG.')
    expected_trips_per_day = fields.Integer(string='Expected Trips / Day')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    vehicle_ids = fields.One2many('transport.vehicle', 'route_id',
                                  string='Vehicles')
    vehicle_count = fields.Integer(compute='_compute_counts')
    cashup_ids = fields.One2many('transport.cashup', 'route_id', string='Cash-Ups')
    cashup_count = fields.Integer(compute='_compute_counts')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'transport.route') or 'New'
        return super().create(vals_list)

    def _compute_counts(self):
        for route in self:
            route.vehicle_count = len(route.vehicle_ids)
            route.cashup_count = len(route.cashup_ids)

    @api.depends('name', 'route_name')
    def _compute_display_name(self):
        for route in self:
            route.display_name = ('[%s] %s' % (route.name, route.route_name)
                                  if route.name and route.name != 'New'
                                  else route.route_name or route.name)

    def action_view_cashups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cash-Ups',
            'res_model': 'transport.cashup',
            'view_mode': 'list,form',
            'domain': [('route_id', '=', self.id)],
            'context': {'default_route_id': self.id},
        }
