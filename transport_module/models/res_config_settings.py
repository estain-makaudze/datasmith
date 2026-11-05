# -*- coding: utf-8 -*-
from odoo import fields, models

from .transport_payment_scheme import PAYMENT_PERIODS


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Cash-up posting -------------------------------------------------
    transport_operations_journal_id = fields.Many2one(
        'account.journal', string='Operations Journal',
        config_parameter='transport_module.operations_journal_id',
        domain="[('type', '=', 'general')]",
        help='Miscellaneous journal that daily cash-up entries are posted to.')
    transport_income_account_id = fields.Many2one(
        'account.account', string='Transport Income Account',
        config_parameter='transport_module.income_account_id',
        help='Income account credited with gross takings.')
    transport_cash_account_id = fields.Many2one(
        'account.account', string='Cash / Undeposited Funds Account',
        config_parameter='transport_module.cash_account_id',
        help='Account debited with the net cash banked from each cash-up.')

    # Driver payments -------------------------------------------------
    transport_wages_journal_id = fields.Many2one(
        'account.journal', string='Wages Journal',
        config_parameter='transport_module.wages_journal_id',
        domain="[('type', '=', 'general')]",
        help='Journal that driver payment runs are posted to.')
    transport_wage_expense_account_id = fields.Many2one(
        'account.account', string='Wage Expense Account',
        config_parameter='transport_module.wage_expense_account_id')
    transport_commission_expense_account_id = fields.Many2one(
        'account.account', string='Commission Expense Account',
        config_parameter='transport_module.commission_expense_account_id',
        help='Leave empty to post commission to the wage expense account.')
    transport_driver_payable_account_id = fields.Many2one(
        'account.account', string='Driver Payable Account',
        config_parameter='transport_module.driver_payable_account_id',
        help='Payable account credited per driver; pay and reconcile each '
             'driver from here.')

    # Defaults --------------------------------------------------------
    transport_default_currency_id = fields.Many2one(
        'res.currency', string='Default Cash-Up Currency',
        config_parameter='transport_module.default_currency_id')
    transport_default_payment_period = fields.Selection(
        PAYMENT_PERIODS, string='Default Payment Period',
        config_parameter='transport_module.default_payment_period',
        default='weekly')
