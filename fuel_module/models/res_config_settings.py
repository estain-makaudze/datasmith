# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fuel_default_tolerance = fields.Float(
        string='Default Wet Stock Tolerance (%)',
        config_parameter='fuel_module.default_tolerance',
        default=0.5,
        help='Variance allowed between book stock and the dip, as a percentage '
             'of throughput. New sites start with this value.')
    fuel_default_currency_id = fields.Many2one(
        'res.currency', string='Default Forecourt Currency',
        config_parameter='fuel_module.default_currency_id',
        help='Currency proposed on new shifts and pump prices (usually USD).')

    # Posting a shift ------------------------------------------------
    fuel_journal_id = fields.Many2one(
        'account.journal', string='Forecourt Journal',
        config_parameter='fuel_module.journal_id',
        domain="[('type', '=', 'general')]",
        help='Journal the one entry per shift is posted to.')
    fuel_sales_account_id = fields.Many2one(
        'account.account', string='Fuel Sales Account',
        config_parameter='fuel_module.sales_account_id',
        help='Income credited with fuel sales, net of VAT. Left empty, the income '
             'account on each grade is used.')
    fuel_tax_id = fields.Many2one(
        'account.tax', string='Output VAT',
        config_parameter='fuel_module.tax_id',
        domain="[('type_tax_use', '=', 'sale')]",
        help='The VAT charged on fuel. Leave empty only if fuel is not taxed.')
    fuel_price_tax_included = fields.Boolean(
        string='Pump Prices Include VAT', default=True,
        config_parameter='fuel_module.price_tax_included',
        help='On in Zimbabwe: the gazetted board price is VAT inclusive.')
    fuel_shortage_account_id = fields.Many2one(
        'account.account', string='Attendant Shortage Account',
        config_parameter='fuel_module.shortage_account_id',
        help='Receivable carrying what an attendant is short, per person.')
    fuel_stock_account_id = fields.Many2one(
        'account.account', string='Fuel Stock Account',
        config_parameter='fuel_module.stock_account_id',
        help='Asset account holding fuel in the ground, at average cost.')
    fuel_cogs_account_id = fields.Many2one(
        'account.account', string='Cost of Sales Account',
        config_parameter='fuel_module.cogs_account_id')
    fuel_stock_loss_account_id = fields.Many2one(
        'account.account', string='Wet Stock Loss Account',
        config_parameter='fuel_module.stock_loss_account_id',
        help='Where an unexplained wet stock variance lands. Owners read this one.')
