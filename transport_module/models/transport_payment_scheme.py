# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

PAYMENT_PERIODS = [
    ('weekly', 'Weekly'),
    ('fortnightly', 'Fortnightly'),
    ('monthly', 'Monthly'),
]

# Kombis run a six-day week; used to pro-rate unpaid leave off the fixed wage.
WORKING_DAYS_PER_PERIOD = {'weekly': 6, 'fortnightly': 12, 'monthly': 26}


class TransportPaymentScheme(models.Model):
    _name = 'transport.payment.scheme'
    _description = 'Driver Payment Scheme'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Name', required=True, tracking=True)
    scheme_type = fields.Selection([
        ('fixed', 'Fixed Wage'),
        ('commission', 'Commission on Takings'),
        ('hybrid', 'Base Wage + Commission'),
    ], string='Type', required=True, default='fixed', tracking=True)
    wage_amount = fields.Monetary(
        string='Wage per Period', currency_field='wage_currency_id', tracking=True,
        help='Fixed (or base) wage paid each payment period.')
    wage_currency_id = fields.Many2one(
        'res.currency', string='Wage Currency',
        default=lambda self: self.env.company.currency_id)
    commission_percent = fields.Float(
        string='Commission (%)', digits=(5, 2), tracking=True,
        help='Percentage of the gross cash the driver collected over the period.')
    payment_period = fields.Selection(
        PAYMENT_PERIODS, string='Payment Period', required=True,
        default='weekly', tracking=True)
    deduct_unpaid_leave = fields.Boolean(
        string='Deduct Unpaid Leave', default=True,
        help='Pro-rate the fixed wage down for approved unpaid leave days '
             'falling inside the payment period.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    driver_ids = fields.One2many('transport.driver', 'payment_scheme_id',
                                 string='Crew')
    driver_count = fields.Integer(compute='_compute_driver_count')

    def _compute_driver_count(self):
        for scheme in self:
            scheme.driver_count = len(scheme.driver_ids)

    @api.constrains('scheme_type', 'wage_amount', 'commission_percent')
    def _check_scheme_amounts(self):
        for scheme in self:
            if scheme.scheme_type in ('fixed', 'hybrid') and scheme.wage_amount <= 0:
                raise ValidationError(_(
                    'Scheme "%s" pays a wage, so the wage per period must be '
                    'greater than zero.') % scheme.name)
            if scheme.scheme_type in ('commission', 'hybrid') and scheme.commission_percent <= 0:
                raise ValidationError(_(
                    'Scheme "%s" pays commission, so the commission percentage '
                    'must be greater than zero.') % scheme.name)
            if scheme.commission_percent > 100:
                raise ValidationError(_(
                    'Commission percentage cannot exceed 100%.'))

    def _working_days(self):
        self.ensure_one()
        return WORKING_DAYS_PER_PERIOD.get(self.payment_period, 6)
