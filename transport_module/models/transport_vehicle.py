# -*- coding: utf-8 -*-
from odoo import api, fields, models


class TransportVehicle(models.Model):
    _name = 'transport.vehicle'
    _description = 'Transport Vehicle'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    _order = 'name'
    _rec_name = 'registration'
    _rec_names_search = ['name', 'registration', 'make', 'model_name']

    name = fields.Char(string='Fleet Number', required=True, copy=False,
                       readonly=True, default='New')
    registration = fields.Char(string='Registration Plate', required=True,
                               tracking=True)
    vehicle_type = fields.Selection([
        ('kombi', 'Kombi (Minibus)'),
        ('bus', 'Bus'),
    ], string='Vehicle Type', required=True, default='kombi', tracking=True)
    make = fields.Char(string='Make', tracking=True)
    model_name = fields.Char(string='Model', tracking=True)
    year = fields.Integer(string='Year')
    seat_capacity = fields.Integer(string='Seat Capacity')
    route_id = fields.Many2one('transport.route', string='Default Route',
                               tracking=True)
    default_driver_id = fields.Many2one(
        'transport.driver', string='Usual Driver', tracking=True,
        domain="[('driver_role', '=', 'driver'), ('state', '=', 'active')]")
    current_odometer = fields.Float(string='Odometer (km)', digits=(12, 1),
                                    tracking=True)
    purchase_date = fields.Date(string='Purchase Date', tracking=True)
    purchase_price = fields.Monetary(
        string='Purchase Price', currency_field='company_currency_id',
        tracking=True, help='What the vehicle was bought for.')
    purchased_from = fields.Char(string='Bought From')
    next_service_date = fields.Date(
        string='Next Service Due', tracking=True,
        help='Updated automatically when a workshop service is completed.')
    next_service_odometer = fields.Float(
        string='Next Service Odometer (km)', digits=(12, 1))
    service_due = fields.Boolean(compute='_compute_service_due',
                                 string='Service Overdue')
    state = fields.Selection([
        ('active', 'On the Road'),
        ('workshop', 'In Workshop'),
        ('retired', 'Retired'),
    ], string='Status', default='active', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')
    cashup_ids = fields.One2many('transport.cashup', 'vehicle_id',
                                 string='Cash-Ups')
    cashup_count = fields.Integer(compute='_compute_cashup_stats')
    total_takings = fields.Monetary(
        string='Total Income', compute='_compute_cashup_stats',
        currency_field='company_currency_id',
        help='Gross takings of confirmed and posted cash-ups, in company currency.')
    total_expenses = fields.Monetary(
        string='Total Expenses', compute='_compute_cashup_stats',
        currency_field='company_currency_id',
        help='Operating expenses of confirmed and posted cash-ups, in company currency.')
    service_ids = fields.One2many('transport.vehicle.service', 'vehicle_id',
                                  string='Services')
    service_count = fields.Integer(compute='_compute_service_stats')
    total_service_cost = fields.Monetary(
        string='Total Service Cost', compute='_compute_service_stats',
        currency_field='company_currency_id',
        help='Cost of completed and posted workshop services, in company currency.')
    net_earnings = fields.Monetary(
        string='Net Earnings', compute='_compute_service_stats',
        currency_field='company_currency_id',
        help='Total income less operating expenses and service costs.')
    amount_to_break_even = fields.Monetary(
        string='Left to Break Even', compute='_compute_service_stats',
        currency_field='company_currency_id',
        help='Purchase price still to be recovered from net earnings.')
    break_even_progress = fields.Float(
        string='Break-Even', compute='_compute_service_stats',
        help='How much of the purchase price the vehicle has earned back, '
             'as a percentage (capped at 100).')
    company_currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'transport.vehicle') or 'New'
        return super().create(vals_list)

    @api.depends('name', 'registration', 'make', 'model_name')
    def _compute_display_name(self):
        for vehicle in self:
            parts = [vehicle.registration or vehicle.name]
            if vehicle.make or vehicle.model_name:
                parts.append(' '.join(filter(None, [vehicle.make, vehicle.model_name])))
            vehicle.display_name = ' – '.join(parts)

    def _compute_cashup_stats(self):
        for vehicle in self:
            company = vehicle.company_id or self.env.company
            vehicle.cashup_count = len(vehicle.cashup_ids)
            sheets = vehicle.cashup_ids.filtered(
                lambda s: s.state in ('confirmed', 'posted'))
            vehicle.total_takings = sum(
                sheet.currency_id._convert(
                    sheet.gross_takings, company.currency_id, company, sheet.date)
                for sheet in sheets)
            vehicle.total_expenses = sum(
                sheet.currency_id._convert(
                    sheet.total_expenses, company.currency_id, company, sheet.date)
                for sheet in sheets)

    def _compute_service_stats(self):
        for vehicle in self:
            vehicle.service_count = len(vehicle.service_ids)
            services = vehicle.service_ids.filtered(
                lambda s: s.state in ('done', 'posted'))
            vehicle.total_service_cost = sum(
                service._to_company_amount(service.total_cost)
                for service in services)
            vehicle.net_earnings = (vehicle.total_takings
                                    - vehicle.total_expenses
                                    - vehicle.total_service_cost)
            vehicle.amount_to_break_even = max(
                vehicle.purchase_price - vehicle.net_earnings, 0.0)
            vehicle.break_even_progress = (
                min(100.0, max(0.0, vehicle.net_earnings
                               / vehicle.purchase_price * 100.0))
                if vehicle.purchase_price else 0.0)

    def _compute_service_due(self):
        today = fields.Date.context_today(self)
        for vehicle in self:
            vehicle.service_due = bool(
                (vehicle.next_service_date
                 and vehicle.next_service_date <= today)
                or (vehicle.next_service_odometer
                    and vehicle.current_odometer
                    >= vehicle.next_service_odometer > 0))

    def action_send_to_service(self):
        """Quick popup: capture what the vehicle is going in for and send it
        to the workshop straight away. Costs are recorded later, when it
        comes back."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send to Service',
            'res_model': 'transport.vehicle.service',
            'view_mode': 'form',
            'views': [(self.env.ref(
                'transport_module.transport_vehicle_service_view_form_quick'
            ).id, 'form')],
            'target': 'new',
            'context': {
                'default_vehicle_id': self.id,
                'default_odometer': self.current_odometer,
            },
        }

    def action_view_services(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Services',
            'res_model': 'transport.vehicle.service',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }

    def action_view_cashups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cash-Ups',
            'res_model': 'transport.cashup',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }
