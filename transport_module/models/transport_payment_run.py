# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .transport_payment_scheme import PAYMENT_PERIODS


class TransportPaymentRun(models.Model):
    _name = 'transport.payment.run'
    _description = 'Driver Payment Run'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_to desc, id desc'
    _rec_names_search = ['name']

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default='New')
    payment_period = fields.Selection(PAYMENT_PERIODS, string='Payment Period',
                                      required=True, default='weekly', tracking=True)
    date_from = fields.Date(string='From', required=True, tracking=True)
    date_to = fields.Date(string='To', required=True, tracking=True)
    currency_id = fields.Many2one(
        'res.currency', string='Payout Currency', required=True, tracking=True,
        default=lambda self: self.env.company.currency_id)
    payment_ids = fields.One2many('transport.driver.payment', 'run_id',
                                  string='Driver Payments')
    total_pay = fields.Monetary(string='Total Payout',
                                compute='_compute_totals', store=True)
    total_commission = fields.Monetary(string='Total Commission',
                                       compute='_compute_totals', store=True)
    driver_count = fields.Integer(compute='_compute_totals', store=True)
    move_id = fields.Many2one('account.move', string='Journal Entry',
                              readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('computed', 'Computed'),
        ('confirmed', 'Confirmed'),
        ('posted', 'Posted'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'transport.payment.run') or 'New'
        return super().create(vals_list)

    @api.depends('payment_ids.total_pay', 'payment_ids.commission_amount')
    def _compute_totals(self):
        for run in self:
            run.total_pay = sum(run.payment_ids.mapped('total_pay'))
            run.total_commission = sum(run.payment_ids.mapped('commission_amount'))
            run.driver_count = len(run.payment_ids)

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    def _get_unpaid_leave_days(self, driver):
        """Approved unpaid-leave working days overlapping the run period."""
        self.ensure_one()
        leaves = self.env['transport.leave'].search([
            ('driver_id', '=', driver.id),
            ('paid', '=', False),
            ('state', '=', 'approved'),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ])
        Leave = self.env['transport.leave']
        days = 0.0
        for leave in leaves:
            overlap_from = max(leave.date_from, self.date_from)
            overlap_to = min(leave.date_to, self.date_to)
            days += Leave._working_days_between(overlap_from, overlap_to)
        return days

    def action_compute(self):
        self.ensure_one()
        if self.state == 'posted':
            raise UserError(_('A posted payment run cannot be recomputed.'))
        self.payment_ids.unlink()

        drivers = self.env['transport.driver'].search([
            ('state', '=', 'active'),
            ('payment_scheme_id.payment_period', '=', self.payment_period),
            ('company_id', 'in', [False, self.company_id.id]),
        ])
        if not drivers:
            raise UserError(_(
                'No active crew members have a %s payment scheme.'
            ) % dict(PAYMENT_PERIODS)[self.payment_period])

        Payment = self.env['transport.driver.payment']
        for driver in drivers:
            scheme = driver.payment_scheme_id
            cashups = self.env['transport.cashup'].search([
                '|', ('driver_id', '=', driver.id),
                ('conductor_id', '=', driver.id),
                ('state', 'in', ('confirmed', 'posted')),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
            ])
            takings_total = 0.0
            for sheet in cashups:
                takings_total += sheet.currency_id._convert(
                    sheet.gross_takings, self.currency_id,
                    self.company_id, sheet.date)

            base_wage = 0.0
            if scheme.scheme_type in ('fixed', 'hybrid'):
                base_wage = scheme.wage_currency_id._convert(
                    scheme.wage_amount, self.currency_id,
                    self.company_id, self.date_to)

            commission = 0.0
            if scheme.scheme_type in ('commission', 'hybrid'):
                commission = takings_total * scheme.commission_percent / 100.0

            unpaid_days = 0.0
            deduction = 0.0
            if base_wage and scheme.deduct_unpaid_leave:
                unpaid_days = self._get_unpaid_leave_days(driver)
                deduction = base_wage * min(
                    unpaid_days / scheme._working_days(), 1.0)

            if not cashups and not base_wage:
                continue  # pure-commission crew with no takings: nothing due

            Payment.create({
                'run_id': self.id,
                'driver_id': driver.id,
                'scheme_id': scheme.id,
                'scheme_type': scheme.scheme_type,
                'base_wage': base_wage,
                'takings_total': takings_total,
                'commission_amount': commission,
                'unpaid_leave_days': unpaid_days,
                'leave_deduction': deduction,
                'total_pay': max(base_wage - deduction, 0.0) + commission,
                'cashup_ids': [(6, 0, cashups.ids)],
            })
        self.state = 'computed'

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def action_confirm(self):
        for run in self:
            if run.state != 'computed':
                raise UserError(_('Compute the run before confirming it.'))
            if not run.payment_ids:
                raise UserError(_('There are no driver payments to confirm.'))
            run.state = 'confirmed'

    def action_post(self):
        for run in self:
            if run.state != 'confirmed':
                raise UserError(_('Only confirmed payment runs can be posted.'))
            if not self.env.su and not self.env.user.has_group(
                    'transport_module.group_transport_manager'):
                raise UserError(_('Only a Transport Manager can post '
                                  'payment runs to Accounting.'))
            move = self.env['account.move'].create(run._prepare_move_vals())
            move._post()
            run.write({'move_id': move.id, 'state': 'posted'})

    def action_draft(self):
        for run in self:
            if run.state == 'posted':
                raise UserError(_('A posted payment run cannot be reset to draft.'))
            run.state = 'draft'

    def action_view_move(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.move_id.id,
        }

    # ------------------------------------------------------------------
    # Accounting integration
    # ------------------------------------------------------------------

    def _prepare_move_vals(self):
        self.ensure_one()
        get_config = self.env['transport.cashup']._get_config_record
        journal = get_config('transport_module.wages_journal_id',
                             'account.journal', _('The Wages journal'))
        wage_account = get_config('transport_module.wage_expense_account_id',
                                  'account.account', _('The Wage Expense account'))
        commission_account_param = self.env['ir.config_parameter'].sudo().get_param(
            'transport_module.commission_expense_account_id')
        commission_account = (
            self.env['account.account'].browse(int(commission_account_param))
            if commission_account_param else wage_account)
        if not commission_account.exists():
            commission_account = wage_account
        payable_account = get_config(
            'transport_module.driver_payable_account_id',
            'account.account', _('The Driver Payable account'))

        company_currency = self.company_id.currency_id
        foreign = self.currency_id != company_currency

        def to_company(amount):
            if not foreign:
                return amount
            return self.currency_id._convert(
                amount, company_currency, self.company_id, self.date_to)

        lines = []

        def line_vals(account, partner, label, amount, company_amount, sign):
            return (0, 0, {
                'account_id': account.id,
                'partner_id': partner.id if partner else False,
                'name': label,
                'debit': company_amount if sign > 0 else 0.0,
                'credit': company_amount if sign < 0 else 0.0,
                'currency_id': self.currency_id.id,
                'amount_currency': amount * sign,
            })

        for payment in self.payment_ids:
            if not payment.total_pay:
                continue
            partner = payment.driver_id.partner_id
            wage_part = max(payment.base_wage - payment.leave_deduction, 0.0)
            # The payable credit takes the exact sum of the driver's debit
            # amounts so the entry balances despite conversion rounding.
            driver_debit = 0.0
            if wage_part:
                company_amount = company_currency.round(to_company(wage_part))
                driver_debit += company_amount
                lines.append(line_vals(
                    wage_account, partner,
                    _('%s – wage %s') % (self.name, payment.driver_id.full_name),
                    wage_part, company_amount, 1))
            if payment.commission_amount:
                company_amount = company_currency.round(
                    to_company(payment.commission_amount))
                driver_debit += company_amount
                lines.append(line_vals(
                    commission_account, partner,
                    _('%s – commission %s') % (self.name,
                                               payment.driver_id.full_name),
                    payment.commission_amount, company_amount, 1))
            lines.append(line_vals(
                payable_account, partner,
                _('%s – payable %s') % (self.name, payment.driver_id.full_name),
                payment.total_pay, company_currency.round(driver_debit), -1))

        if not lines:
            raise UserError(_('There is nothing to post: all payments are zero.'))

        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date_to,
            'ref': _('Driver payments %s (%s – %s)') % (
                self.name, self.date_from, self.date_to),
            'line_ids': lines,
        }


class TransportDriverPayment(models.Model):
    _name = 'transport.driver.payment'
    _description = 'Driver Payment Line'
    _order = 'driver_id'

    run_id = fields.Many2one('transport.payment.run', string='Payment Run',
                             required=True, ondelete='cascade')
    driver_id = fields.Many2one('transport.driver', string='Crew Member',
                                required=True)
    scheme_id = fields.Many2one('transport.payment.scheme', string='Scheme')
    scheme_type = fields.Selection([
        ('fixed', 'Fixed Wage'),
        ('commission', 'Commission on Takings'),
        ('hybrid', 'Base Wage + Commission'),
    ], string='Scheme Type')
    currency_id = fields.Many2one(related='run_id.currency_id')
    base_wage = fields.Monetary(string='Base Wage')
    takings_total = fields.Monetary(
        string='Cash Collected',
        help='Gross takings of the crew member\'s confirmed cash-ups over '
             'the period, converted to the payout currency.')
    commission_amount = fields.Monetary(string='Commission')
    unpaid_leave_days = fields.Float(string='Unpaid Leave (days)', digits=(5, 1))
    leave_deduction = fields.Monetary(string='Leave Deduction')
    total_pay = fields.Monetary(string='Total Pay')
    cashup_ids = fields.Many2many('transport.cashup', string='Cash-Ups Counted')
    cashup_count = fields.Integer(compute='_compute_cashup_count')

    def _compute_cashup_count(self):
        for payment in self:
            payment.cashup_count = len(payment.cashup_ids)

    def action_view_cashups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cash-Ups – %s') % self.driver_id.full_name,
            'res_model': 'transport.cashup',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.cashup_ids.ids)],
        }
