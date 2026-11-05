# -*- coding: utf-8 -*-
from odoo import fields, models


class FreightTransporter(models.Model):
    """A sub-contracted trucker who moves cleared goods on behalf of the agent.

    Extends `res.partner` so Odoo's payables and bank/EcoCash payment
    reconciliation apply. Flagged with `is_freight_transporter`; a trip
    posted on a consignment creates the payable on this partner.
    """
    _inherit = 'res.partner'

    is_freight_transporter = fields.Boolean(
        string='Is Transporter',
        help='Tick to show this partner in the Freight > Transporters list.')
    freight_truck_regs = fields.Char(
        string='Truck Reg(s)',
        help='Comma-separated truck registrations.')
    freight_rate_per_km = fields.Monetary(
        string='Rate / km', currency_field='freight_currency_id',
        help='Default rate per kilometre; overridden on each trip.')
    freight_flat_rate = fields.Monetary(
        string='Flat Rate', currency_field='freight_currency_id',
        help='Default flat rate for common lanes; overridden on each trip.')
    freight_currency_id = fields.Many2one(
        'res.currency', string='Rate Currency',
        default=lambda self: self.env.company.currency_id)
    freight_notes_transporter = fields.Text(string='Transporter Notes')
