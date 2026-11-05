# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FreightHsCode(models.Model):
    """ZIMRA tariff heading (HS code) with duty, VAT and surtax rates.

    HS lines on a consignment pull their rates from here. Agents can
    maintain their own working subset; the full ZIMRA tariff is thousands
    of lines, we seed only the common ones and the agent adds the rest as
    they encounter them.
    """
    _name = 'freight.hs.code'
    _description = 'HS Tariff Code'
    _order = 'code'
    _rec_names_search = ['code', 'description']

    code = fields.Char(string='HS Code', required=True, size=20,
                       help='The tariff heading, e.g. 8703.23.00')
    description = fields.Char(string='Description', required=True)
    unit = fields.Char(string='Unit', help='Unit of measure, e.g. kg, each, L.')
    duty_rate = fields.Float(string='Customs Duty %', digits=(5, 2),
                             help='Customs duty rate applicable to this tariff heading.')
    vat_rate = fields.Float(string='VAT %', digits=(5, 2), default=15.0,
                            help='VAT rate; typically 15% standard, 0% zero-rated, blank for exempt.')
    surtax_rate = fields.Float(string='Surtax %', digits=(5, 2),
                               help='ZIMRA surtax on applicable goods, e.g. second-hand vehicles.')
    cbca_applies = fields.Boolean(
        string='CBCA Required',
        help='Consignment-Based Conformity Assessment inspection required by SAZ.')
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('code_uniq', 'UNIQUE(code)', 'HS code must be unique.'),
    ]

    @api.depends('code', 'description')
    def _compute_display_name(self):
        for hs in self:
            hs.display_name = '%s — %s' % (hs.code, hs.description or '')
