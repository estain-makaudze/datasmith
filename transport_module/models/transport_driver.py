# -*- coding: utf-8 -*-
from odoo import api, fields, models


class TransportDriver(models.Model):
    _name = 'transport.driver'
    _description = 'Transport Driver / Conductor'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    _order = 'full_name'
    _rec_name = 'full_name'
    _rec_names_search = ['name', 'full_name', 'id_number', 'license_number']

    name = fields.Char(string='Crew Number', required=True, copy=False,
                       readonly=True, default='New')
    full_name = fields.Char(string='Name', required=True, tracking=True)
    driver_role = fields.Selection([
        ('driver', 'Driver'),
        ('conductor', 'Conductor'),
    ], string='Role', required=True, default='driver', tracking=True)
    id_number = fields.Char(string='National ID', tracking=True)
    license_number = fields.Char(string='Licence Number', tracking=True)
    license_class = fields.Char(string='Licence Class', tracking=True)
    license_expiry = fields.Date(string='Licence Expiry', tracking=True)
    defensive_cert_expiry = fields.Date(
        string='Defensive Driving Cert Expiry', tracking=True)
    phone = fields.Char(string='Phone')
    address = fields.Char(string='Address')
    hire_date = fields.Date(string='Hired On', tracking=True)
    payment_scheme_id = fields.Many2one(
        'transport.payment.scheme', string='Payment Scheme', tracking=True,
        help='How this crew member is paid: fixed wage, commission on cash '
             'collected, or a hybrid of both.')
    default_vehicle_id = fields.Many2one('transport.vehicle',
                                         string='Usual Vehicle', tracking=True)
    state = fields.Selection([
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('left', 'Left'),
    ], string='Status', default='active', required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    # Accounting touchpoint: every crew member carries a partner so payment
    # runs can post per-driver payable lines that are paid and reconciled
    # individually in Accounting.
    partner_id = fields.Many2one('res.partner', string='Accounting Partner',
                                 readonly=True, copy=False)

    leave_allocation_ids = fields.One2many('transport.leave.allocation',
                                           'driver_id', string='Leave Allocations')
    leave_ids = fields.One2many('transport.leave', 'driver_id', string='Leaves')
    leave_count = fields.Integer(compute='_compute_counts')
    cashup_count = fields.Integer(compute='_compute_counts')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'transport.driver') or 'New'
        records = super().create(vals_list)
        for driver in records.filtered(lambda d: not d.partner_id):
            driver.partner_id = self.env['res.partner'].create({
                'name': driver.full_name,
                'phone': driver.phone,
                'company_type': 'person',
            })
        return records

    def write(self, vals):
        res = super().write(vals)
        if 'full_name' in vals:
            for driver in self.filtered('partner_id'):
                driver.partner_id.name = driver.full_name
        return res

    def _compute_counts(self):
        Cashup = self.env['transport.cashup']
        for driver in self:
            driver.leave_count = len(driver.leave_ids)
            driver.cashup_count = Cashup.search_count([
                '|', ('driver_id', '=', driver.id),
                ('conductor_id', '=', driver.id),
            ])

    def action_view_cashups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cash-Ups',
            'res_model': 'transport.cashup',
            'view_mode': 'list,form',
            'domain': ['|', ('driver_id', '=', self.id),
                       ('conductor_id', '=', self.id)],
            'context': {'default_driver_id': self.id},
        }

    def action_view_leaves(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Leave Requests',
            'res_model': 'transport.leave',
            'view_mode': 'list,form',
            'domain': [('driver_id', '=', self.id)],
            'context': {'default_driver_id': self.id},
        }
