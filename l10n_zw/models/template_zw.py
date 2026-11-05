from odoo import models
from odoo.addons.account.models.chart_template import template


class AccountChartTemplate(models.AbstractModel):
    _inherit = 'account.chart.template'

    @template('zw')
    def _get_zw_template_data(self):
        return {
            'name': 'Zimbabwe',
            'property_account_receivable_id': 'zw1100',
            'property_account_payable_id': 'zw2100',
            'code_digits': '6',
        }

    @template('zw', 'res.company')
    def _get_zw_res_company(self):
        return {
            self.env.company.id: {
                'account_fiscal_country_id': 'base.zw',
                'bank_account_code_prefix': '1200',
                'cash_account_code_prefix': '1250',
                'transfer_account_code_prefix': '1210',
                'account_default_pos_receivable_account_id': 'zw1101',
                'income_currency_exchange_account_id': 'zw4500',
                'expense_currency_exchange_account_id': 'zw5500',
                'default_cash_difference_income_account_id': 'zw4501',
                'default_cash_difference_expense_account_id': 'zw5501',
                'account_sale_tax_id': 'ZWST155',
                'account_purchase_tax_id': 'ZWPT155',
            },
        }
