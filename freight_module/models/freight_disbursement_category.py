# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FreightDisbursementCategory(models.Model):
    """Category of an out-of-pocket payment made on behalf of a client.

    Every captured disbursement is classified. The category drives the
    account posting (expense vs. passthrough), whether it is billable by
    default, and how it appears on the client-facing status page.
    """
    _name = 'freight.disbursement.category'
    _description = 'Disbursement Category'
    _order = 'sequence, name'

    name = fields.Char(string='Category', required=True, translate=True)
    code = fields.Char(string='Code', required=True, size=16,
                       help='Short code used on receipts and reports, e.g. DUTY, VAT, PORT.')
    sequence = fields.Integer(default=10)
    kind = fields.Selection([
        ('duty', 'Customs Duty'),
        ('vat', 'Import VAT'),
        ('surtax', 'Surtax'),
        ('inspection', 'Inspection / CBCA'),
        ('port', 'Port Handling'),
        ('storage', 'Storage'),
        ('demurrage', 'Demurrage'),
        ('transport', 'Transport'),
        ('escort', 'Escort / Convoy'),
        ('scanning', 'Scanning'),
        ('warehouse', 'Warehouse'),
        ('other', 'Other'),
    ], string='Kind', required=True, default='other',
       help='Groups categories for reporting and dashboard aggregation.')
    billable_default = fields.Boolean(
        string='Billable by Default', default=True,
        help='New disbursements under this category are billable to the client '
             'unless the clerk unticks the flag on the line.')
    show_on_status_page = fields.Boolean(
        string='Show on Client Status Page', default=True,
        help='Appears in the running cost summary the importer sees.')
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('code_uniq', 'UNIQUE(code)',
         'Disbursement category code must be unique.'),
    ]

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for cat in self:
            cat.display_name = '%s' % (cat.name,)
