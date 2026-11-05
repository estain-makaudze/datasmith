# -*- coding: utf-8 -*-
from odoo import api, fields, models


class FreightHsLine(models.Model):
    """A tariff line on a consignment.

    Each line picks an HS code, inherits its duty/VAT/surtax rates (which
    the clerk can override if the goods qualify for a rebate), and
    computes the duty, VAT and surtax amounts. The sum across all lines
    is the estimated duty on the consignment and feeds the quote.
    """
    _name = 'freight.hs.line'
    _description = 'Consignment HS Line'
    _order = 'sequence, id'

    consignment_id = fields.Many2one(
        'freight.consignment', string='Consignment', required=True,
        ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    hs_code_id = fields.Many2one(
        'freight.hs.code', string='HS Code', required=True)
    description = fields.Char(string='Description')
    unit = fields.Char(string='Unit')
    qty = fields.Float(string='Qty', digits=(16, 3), default=1.0)
    value = fields.Monetary(
        string='Line Value', required=True,
        currency_field='currency_id',
        help='Customs value in the invoice currency.')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        related='consignment_id.invoice_currency_id', store=True,
        readonly=True)

    duty_rate = fields.Float(string='Duty %', digits=(5, 2))
    vat_rate = fields.Float(string='VAT %', digits=(5, 2))
    surtax_rate = fields.Float(string='Surtax %', digits=(5, 2))

    duty_amount = fields.Monetary(
        string='Duty', compute='_compute_amounts', store=True,
        currency_field='currency_id')
    vat_amount = fields.Monetary(
        string='VAT', compute='_compute_amounts', store=True,
        currency_field='currency_id')
    surtax_amount = fields.Monetary(
        string='Surtax', compute='_compute_amounts', store=True,
        currency_field='currency_id')
    total_due = fields.Monetary(
        string='Total Due', compute='_compute_amounts', store=True,
        currency_field='currency_id',
        help='Customs duty + VAT + surtax on this line.')

    @api.onchange('hs_code_id')
    def _onchange_hs_code(self):
        for line in self:
            if line.hs_code_id:
                line.description = (line.description
                                    or line.hs_code_id.description)
                line.unit = line.unit or line.hs_code_id.unit
                line.duty_rate = line.hs_code_id.duty_rate
                line.vat_rate = line.hs_code_id.vat_rate
                line.surtax_rate = line.hs_code_id.surtax_rate

    @api.depends('value', 'duty_rate', 'vat_rate', 'surtax_rate')
    def _compute_amounts(self):
        for line in self:
            value = line.value or 0.0
            line.duty_amount = value * (line.duty_rate or 0.0) / 100.0
            dutiable = value + line.duty_amount + (
                value * (line.surtax_rate or 0.0) / 100.0)
            line.surtax_amount = value * (line.surtax_rate or 0.0) / 100.0
            line.vat_amount = dutiable * (line.vat_rate or 0.0) / 100.0
            line.total_due = (line.duty_amount
                              + line.vat_amount
                              + line.surtax_amount)
