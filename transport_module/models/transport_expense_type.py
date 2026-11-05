# -*- coding: utf-8 -*-
from odoo import fields, models


class TransportExpenseType(models.Model):
    _name = 'transport.expense.type'
    _description = 'Transport Operating Expense Type'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    account_id = fields.Many2one(
        'account.account', string='Expense Account',
        help='General ledger account this expense is posted to when a '
             'cash-up sheet is posted to Accounting.')
    requires_reference = fields.Boolean(
        string='Requires Reference',
        help='Tick for expenses that must carry a receipt or ticket number, '
             'e.g. police fines or tollgate receipts.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
