# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class TransportCashup(models.Model):
    _name = 'transport.cashup'
    _description = 'Daily Cash-Up Sheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'
    _rec_names_search = ['name']

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default='New')
    date = fields.Date(string='Date', required=True,
                       default=fields.Date.context_today, tracking=True)
    shift = fields.Selection([
        ('full_day', 'Full Day'),
        ('morning', 'Morning'),
        ('evening', 'Evening'),
    ], string='Shift', required=True, default='full_day', tracking=True)
    vehicle_id = fields.Many2one('transport.vehicle', string='Vehicle',
                                 required=True, tracking=True)
    route_id = fields.Many2one('transport.route', string='Route', tracking=True)
    driver_id = fields.Many2one(
        'transport.driver', string='Driver', required=True, tracking=True,
        domain="[('driver_role', '=', 'driver'), ('state', '=', 'active')]")
    conductor_id = fields.Many2one(
        'transport.driver', string='Conductor', tracking=True,
        domain="[('state', '=', 'active')]")
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True, tracking=True,
        default=lambda self: self._default_currency())
    trips_count = fields.Integer(string='Trips Made')
    gross_takings = fields.Monetary(string='Gross Takings', tracking=True,
                                    help='Total cash collected before expenses.')
    expense_line_ids = fields.One2many('transport.cashup.expense', 'cashup_id',
                                       string='Operating Expenses')
    total_expenses = fields.Monetary(string='Total Expenses',
                                     compute='_compute_amounts', store=True)
    net_amount = fields.Monetary(string='Net Banked',
                                 compute='_compute_amounts', store=True,
                                 help='Gross takings less operating expenses.')
    move_id = fields.Many2one('account.move', string='Journal Entry',
                              readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    @api.model
    def _default_currency(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'transport_module.default_currency_id')
        if param:
            currency = self.env['res.currency'].browse(int(param))
            if currency.exists():
                return currency
        return self.env.company.currency_id

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'transport.cashup') or 'New'
        return super().create(vals_list)

    @api.depends('gross_takings', 'expense_line_ids.amount')
    def _compute_amounts(self):
        for sheet in self:
            sheet.total_expenses = sum(sheet.expense_line_ids.mapped('amount'))
            sheet.net_amount = sheet.gross_takings - sheet.total_expenses

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id:
            if self.vehicle_id.route_id:
                self.route_id = self.vehicle_id.route_id
            if self.vehicle_id.default_driver_id:
                self.driver_id = self.vehicle_id.default_driver_id

    @api.constrains('gross_takings')
    def _check_gross_takings(self):
        for sheet in self:
            if sheet.gross_takings < 0:
                raise ValidationError(_('Gross takings cannot be negative.'))

    @api.constrains('vehicle_id', 'date', 'shift', 'state')
    def _check_unique_vehicle_day_shift(self):
        for sheet in self:
            if sheet.state == 'cancelled':
                continue
            duplicate = self.search_count([
                ('id', '!=', sheet.id),
                ('vehicle_id', '=', sheet.vehicle_id.id),
                ('date', '=', sheet.date),
                ('shift', '=', sheet.shift),
                ('state', '!=', 'cancelled'),
            ], limit=1)
            if duplicate:
                raise ValidationError(_(
                    'Vehicle %s already has a cash-up for %s (%s shift).') % (
                    sheet.vehicle_id.display_name, sheet.date, sheet.shift))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def action_confirm(self):
        for sheet in self:
            if sheet.state != 'draft':
                raise UserError(_('Only draft cash-ups can be confirmed.'))
            missing_ref = sheet.expense_line_ids.filtered(
                lambda l: l.expense_type_id.requires_reference and not l.reference)
            if missing_ref:
                raise UserError(_(
                    'Expense "%s" requires a receipt/reference number.'
                ) % missing_ref[0].expense_type_id.name)
            sheet.state = 'confirmed'

    def action_post(self):
        for sheet in self:
            if sheet.state != 'confirmed':
                raise UserError(_('Only confirmed cash-ups can be posted.'))
            if not self.env.su and not self.env.user.has_group(
                    'transport_module.group_transport_manager'):
                raise UserError(_('Only a Transport Manager can post '
                                  'cash-ups to Accounting.'))
            move = self.env['account.move'].create(sheet._prepare_move_vals())
            move._post()
            sheet.write({'move_id': move.id, 'state': 'posted'})

    def action_cancel(self):
        for sheet in self:
            if sheet.state == 'posted':
                raise UserError(_(
                    'A posted cash-up cannot be cancelled. Reverse its journal '
                    'entry from Accounting first.'))
            sheet.state = 'cancelled'

    def action_draft(self):
        for sheet in self:
            if sheet.state == 'posted':
                raise UserError(_('A posted cash-up cannot be reset to draft.'))
            sheet.state = 'draft'

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

    @api.model
    def _get_config_record(self, param, model, label):
        """Fetch a configured journal/account from system parameters."""
        value = self.env['ir.config_parameter'].sudo().get_param(param)
        record = self.env[model].browse(int(value)) if value else self.env[model]
        if not record.exists():
            raise UserError(_(
                '%s is not configured. Set it under Transport '
                '▸ Configuration ▸ Settings.') % label)
        return record

    def _to_company_amount(self, amount):
        self.ensure_one()
        company_currency = self.company_id.currency_id
        if self.currency_id == company_currency:
            return amount
        return self.currency_id._convert(
            amount, company_currency, self.company_id, self.date)

    def _prepare_move_vals(self):
        self.ensure_one()
        journal = self._get_config_record(
            'transport_module.operations_journal_id', 'account.journal',
            _('The Operations journal'))
        income_account = self._get_config_record(
            'transport_module.income_account_id', 'account.account',
            _('The Transport Income account'))
        cash_account = self._get_config_record(
            'transport_module.cash_account_id', 'account.account',
            _('The Cash / Undeposited Funds account'))
        partner = self.driver_id.partner_id

        lines = []
        company_currency = self.company_id.currency_id
        total_debit = 0.0

        def add_debit(account, label, amount):
            nonlocal total_debit
            company_amount = company_currency.round(
                self._to_company_amount(amount))
            total_debit += company_amount
            lines.append((0, 0, {
                'account_id': account.id,
                'name': label,
                'partner_id': partner.id if partner else False,
                'debit': company_amount,
                'credit': 0.0,
                'currency_id': self.currency_id.id,
                'amount_currency': amount,
            }))

        add_debit(cash_account,
                  _('%s – net banked') % self.name, self.net_amount)
        for expense in self.expense_line_ids:
            account = expense.expense_type_id.account_id
            if not account:
                raise UserError(_(
                    'Expense type "%s" has no expense account configured.'
                ) % expense.expense_type_id.name)
            label = expense.description or expense.expense_type_id.name
            if expense.reference:
                label = '%s (%s)' % (label, expense.reference)
            add_debit(account, label, expense.amount)
        # Credit the full gross to income; the company-currency side is the
        # exact sum of the debits so the entry balances despite per-line
        # conversion rounding on foreign-currency sheets.
        lines.append((0, 0, {
            'account_id': income_account.id,
            'name': _('%s – gross takings') % self.name,
            'partner_id': partner.id if partner else False,
            'debit': 0.0,
            'credit': company_currency.round(total_debit),
            'currency_id': self.currency_id.id,
            'amount_currency': -self.gross_takings,
        }))

        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': '%s / %s / %s' % (
                self.name, self.vehicle_id.registration,
                self.driver_id.full_name),
            'line_ids': lines,
        }


class TransportCashupExpense(models.Model):
    _name = 'transport.cashup.expense'
    _description = 'Cash-Up Expense Line'

    cashup_id = fields.Many2one('transport.cashup', string='Cash-Up',
                                required=True, ondelete='cascade')
    expense_type_id = fields.Many2one('transport.expense.type',
                                      string='Expense Type', required=True)
    description = fields.Char(string='Description')
    reference = fields.Char(string='Receipt / Reference')
    currency_id = fields.Many2one(related='cashup_id.currency_id')
    amount = fields.Monetary(string='Amount', required=True)

    _amount_positive = models.Constraint(
        'CHECK(amount >= 0)',
        'Expense amount cannot be negative.',
    )
