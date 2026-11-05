# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models

from ..models.transport_payment_scheme import PAYMENT_PERIODS


class TransportPaymentRunWizard(models.TransientModel):
    _name = 'transport.payment.run.wizard'
    _description = 'Run Driver Payments'

    payment_period = fields.Selection(
        PAYMENT_PERIODS, string='Payment Period', required=True,
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param(
            'transport_module.default_payment_period', 'weekly'))
    date_from = fields.Date(string='From', required=True)
    date_to = fields.Date(string='To', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='Payout Currency', required=True,
        default=lambda self: self.env.company.currency_id)

    @api.onchange('payment_period')
    def _onchange_payment_period(self):
        """Suggest the last complete period ending before today."""
        today = fields.Date.context_today(self)
        if self.payment_period == 'monthly':
            first_of_month = today.replace(day=1)
            self.date_to = first_of_month - timedelta(days=1)
            self.date_from = self.date_to.replace(day=1)
        else:
            days = 7 if self.payment_period == 'weekly' else 14
            # Last complete Monday-to-Sunday span.
            last_sunday = today - timedelta(days=today.weekday() + 1)
            self.date_to = last_sunday
            self.date_from = last_sunday - timedelta(days=days - 1)

    def action_create_run(self):
        self.ensure_one()
        run = self.env['transport.payment.run'].create({
            'payment_period': self.payment_period,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'currency_id': self.currency_id.id,
        })
        run.action_compute()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'transport.payment.run',
            'view_mode': 'form',
            'res_id': run.id,
        }
