# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Disbursement posting -------------------------------------------------
    freight_disbursement_journal_id = fields.Many2one(
        'account.journal', string='Disbursement Journal',
        config_parameter='freight_module.disbursement_journal_id',
        domain="[('type', 'in', ('cash', 'bank'))]",
        help='Cash/bank journal used to record payments the agent makes on '
             'behalf of clients (duties, port fees, transporter, scanning).')
    freight_client_disbursements_account_id = fields.Many2one(
        'account.account', string='Client Disbursements Receivable',
        config_parameter='freight_module.client_disbursements_account_id',
        help='Receivable account debited when a disbursement is paid on '
             'behalf of a client, and cleared when billed into the service '
             'invoice.')

    # Service invoicing ----------------------------------------------------
    freight_clearing_revenue_journal_id = fields.Many2one(
        'account.journal', string='Clearing Revenue Journal',
        config_parameter='freight_module.clearing_revenue_journal_id',
        domain="[('type', '=', 'sale')]",
        help='Sales journal that fiscalised service invoices post to.')
    freight_clearing_revenue_account_id = fields.Many2one(
        'account.account', string='Clearing Revenue Account',
        config_parameter='freight_module.clearing_revenue_account_id',
        help='Income account credited with the clearing agent fee.')

    # Client deposits ------------------------------------------------------
    freight_client_deposits_journal_id = fields.Many2one(
        'account.journal', string='Deposits Journal',
        config_parameter='freight_module.client_deposits_journal_id',
        domain="[('type', 'in', ('cash', 'bank'))]",
        help='Journal that client advance deposits are received into.')
    freight_client_deposits_account_id = fields.Many2one(
        'account.account', string='Client Deposits Liability',
        config_parameter='freight_module.client_deposits_account_id',
        help='Liability account credited when a client pays an advance deposit, '
             'and debited when the deposit is applied to a service invoice.')

    # Transport sub-contractors --------------------------------------------
    freight_transport_cost_account_id = fields.Many2one(
        'account.account', string='Transport Cost Account',
        config_parameter='freight_module.transport_cost_account_id',
        help='Cost of sales account debited when a trip is approved for payment '
             'to the sub-contracted transporter.')

    # FX ------------------------------------------------------------------
    freight_fx_gain_account_id = fields.Many2one(
        'account.account', string='FX Gain / Loss Account',
        config_parameter='freight_module.fx_gain_account_id',
        help='Account used to post FX gain or loss on reconciliation of '
             'disbursements paid in one currency vs client deposits in another.')

    # Defaults -------------------------------------------------------------
    freight_default_currency_id = fields.Many2one(
        'res.currency', string='Default Operating Currency',
        config_parameter='freight_module.default_currency_id',
        help='Currency proposed on new consignments and quotes (typically USD).')
    freight_default_free_days = fields.Integer(
        string='Default Free Days at Port', default=5,
        config_parameter='freight_module.default_free_days',
        help='Fallback free-days allowance when a port record does not specify.')
