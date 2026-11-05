# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FreightPort(models.Model):
    """A port of entry or exit: border post, sea port, airport.

    Each port carries its own free-days allowance and daily demurrage
    rate — these feed the demurrage countdown clock on a consignment
    once it is in that port's custody.
    """
    _name = 'freight.port'
    _description = 'Port / Entry Point'
    _order = 'mode, name'
    _rec_names_search = ['name', 'code']

    name = fields.Char(string='Port Name', required=True)
    code = fields.Char(string='Code', required=True, size=8,
                       help='Short code used on consignments, e.g. BBR, CHR, DUR.')
    mode = fields.Selection([
        ('road', 'Road Border'),
        ('sea', 'Sea Port'),
        ('air', 'Airport'),
    ], string='Mode', required=True, default='road')
    country_id = fields.Many2one('res.country', string='Country',
                                 default=lambda self: self.env.ref(
                                     'base.zw', raise_if_not_found=False))
    free_days = fields.Integer(
        string='Free Days', default=5, required=True,
        help='Number of calendar days a consignment can sit at this port '
             'before demurrage starts accruing.')
    demurrage_daily_rate = fields.Monetary(
        string='Demurrage per Day',
        currency_field='demurrage_currency_id',
        help='Daily cost charged by the port operator once free days expire.')
    demurrage_currency_id = fields.Many2one(
        'res.currency', string='Demurrage Currency',
        default=lambda self: self.env.company.currency_id)
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('code_uniq', 'UNIQUE(code)',
         'Port code must be unique.'),
    ]

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for port in self:
            port.display_name = ('[%s] %s' % (port.code, port.name)
                                 if port.code else port.name)
