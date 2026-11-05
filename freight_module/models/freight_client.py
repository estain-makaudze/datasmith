# -*- coding: utf-8 -*-
from odoo import fields, models


class FreightClient(models.Model):
    """An importer / exporter the clearing agent works for.

    Implemented as an extension of `res.partner` so Odoo's receivables,
    partner ledgers and reconciliation work out of the box. Flagged with
    `is_freight_client`; the Freight menu filters partner views on this
    flag.
    """
    _inherit = 'res.partner'

    is_freight_client = fields.Boolean(
        string='Is Freight Client',
        help='Tick to show this partner in the Freight > Clients list.')
    freight_tin = fields.Char(
        string='TIN',
        help='Tax Identification Number issued by ZIMRA. Appears on the '
             'Bill of Entry and the fiscalised invoice.')
    freight_bp_number = fields.Char(
        string='BP Number',
        help='ZIMRA Business Partner number.')
    freight_default_incoterm = fields.Selection([
        ('exw', 'EXW — Ex Works'),
        ('fob', 'FOB — Free on Board'),
        ('cif', 'CIF — Cost, Insurance, Freight'),
        ('cfr', 'CFR — Cost and Freight'),
        ('dap', 'DAP — Delivered at Place'),
        ('ddp', 'DDP — Delivered Duty Paid'),
    ], string='Default Incoterm')
    freight_notes = fields.Text(string='Client Notes (Freight)')
