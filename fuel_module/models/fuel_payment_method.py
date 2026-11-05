# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FuelPaymentMethod(models.Model):
    _name = 'fuel.payment.method'
    _description = 'Forecourt Payment Method'
    _order = 'sequence, name'

    name = fields.Char(string='Method', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    kind = fields.Selection(
        [('cash', 'Cash'),
         ('mobile', 'Mobile Money'),
         ('card', 'Card or Swipe'),
         ('coupon', 'Coupon'),
         ('docket', 'Fleet Docket'),
         ('other', 'Other')],
        string='Kind', required=True, default='cash',
        help='Decides how the money is treated. Fleet dockets are a debt, not cash.')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        help='Fixes the currency for this method, e.g. Cash ZiG. Leave empty to let '
             'the attendant choose.')
    requires_reference = fields.Boolean(
        string='Needs a Reference',
        help='Tick for mobile money and swipe, where a transaction reference can be '
             'verified later.')
    account_id = fields.Many2one(
        'account.account', string='Clearing Account',
        help='Debited with what this method took in. Cash sits here until the '
             'banking run clears it, which is what unbanked cash means.')
    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)

    _code_uniq = models.Constraint(
        'UNIQUE(code, company_id)',
        'Another payment method already uses that code.',
    )

    @api.depends('name', 'currency_id')
    def _compute_display_name(self):
        for method in self:
            method.display_name = (
                '%s (%s)' % (method.name, method.currency_id.name)
                if method.currency_id else method.name)
