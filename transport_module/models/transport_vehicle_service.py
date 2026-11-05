# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class TransportVehicleService(models.Model):
    _name = 'transport.vehicle.service'
    _description = 'Vehicle Service / Workshop Visit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_sent desc, id desc'
    _rec_names_search = ['name', 'workshop_name']

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default='New')
    vehicle_id = fields.Many2one('transport.vehicle', string='Vehicle',
                                 required=True, tracking=True)
    description = fields.Char(string='Work Requested', required=True,
                              tracking=True,
                              help='e.g. Full service, brake overhaul, clutch.')
    workshop_name = fields.Char(string='Workshop / Garage', tracking=True)
    date_sent = fields.Date(string='Date Sent', required=True,
                            default=fields.Date.context_today, tracking=True)
    date_returned = fields.Date(string='Date Returned', tracking=True)
    odometer = fields.Float(string='Odometer at Service (km)', digits=(12, 1))
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True, tracking=True,
        default=lambda self: self.env['transport.cashup']._default_currency())
    line_ids = fields.One2many('transport.vehicle.service.line', 'service_id',
                               string='Service Expenses')
    total_cost = fields.Monetary(string='Total Cost',
                                 compute='_compute_total_cost', store=True)
    next_service_date = fields.Date(
        string='Next Service Due', tracking=True,
        help='Copied to the vehicle when the service is completed.')
    next_service_odometer = fields.Float(
        string='Next Service Odometer (km)', digits=(12, 1))
    move_id = fields.Many2one('account.move', string='Journal Entry',
                              readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_service', 'In Workshop'),
        ('done', 'Completed'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, tracking=True,
        copy=False)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'transport.vehicle.service') or 'New'
        return super().create(vals_list)

    @api.depends('line_ids.amount')
    def _compute_total_cost(self):
        for service in self:
            service.total_cost = sum(service.line_ids.mapped('amount'))

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id(self):
        if self.vehicle_id:
            self.odometer = self.vehicle_id.current_odometer

    @api.constrains('date_sent', 'date_returned')
    def _check_dates(self):
        for service in self:
            if (service.date_returned
                    and service.date_returned < service.date_sent):
                raise ValidationError(_(
                    'The return date cannot be before the date sent.'))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def action_send(self):
        """Send the vehicle to the workshop."""
        for service in self:
            if service.state != 'draft':
                raise UserError(_('Only draft services can be sent.'))
            service.state = 'in_service'
            service.vehicle_id.state = 'workshop'

    def action_done(self):
        """Vehicle is back on the road; roll the service plan forward."""
        for service in self:
            if service.state != 'in_service':
                raise UserError(_(
                    'Only vehicles in the workshop can be marked returned.'))
            if not service.date_returned:
                service.date_returned = fields.Date.context_today(service)
            service.state = 'done'
            vehicle_vals = {'state': 'active'}
            if service.next_service_date:
                vehicle_vals['next_service_date'] = service.next_service_date
            if service.next_service_odometer:
                vehicle_vals['next_service_odometer'] = \
                    service.next_service_odometer
            if service.odometer > service.vehicle_id.current_odometer:
                vehicle_vals['current_odometer'] = service.odometer
            service.vehicle_id.write(vehicle_vals)

    def action_post(self):
        for service in self:
            if service.state != 'done':
                raise UserError(_(
                    'Only completed services can be posted to Accounting.'))
            if not service.line_ids:
                raise UserError(_(
                    'Add at least one service expense line before posting.'))
            if not self.env.su and not self.env.user.has_group(
                    'transport_module.group_transport_manager'):
                raise UserError(_('Only a Transport Manager can post '
                                  'services to Accounting.'))
            move = self.env['account.move'].create(
                service._prepare_move_vals())
            move._post()
            service.write({'move_id': move.id, 'state': 'posted'})

    def action_cancel(self):
        for service in self:
            if service.state == 'posted':
                raise UserError(_(
                    'A posted service cannot be cancelled. Reverse its '
                    'journal entry from Accounting first.'))
            if service.state == 'in_service':
                service.vehicle_id.state = 'active'
            service.state = 'cancelled'

    def action_draft(self):
        for service in self:
            if service.state == 'posted':
                raise UserError(_(
                    'A posted service cannot be reset to draft.'))
            service.state = 'draft'

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

    def _to_company_amount(self, amount):
        self.ensure_one()
        company_currency = self.company_id.currency_id
        if self.currency_id == company_currency:
            return amount
        return self.currency_id._convert(
            amount, company_currency, self.company_id,
            self.date_returned or self.date_sent)

    def _prepare_move_vals(self):
        self.ensure_one()
        Cashup = self.env['transport.cashup']
        journal = Cashup._get_config_record(
            'transport_module.operations_journal_id', 'account.journal',
            _('The Operations journal'))
        cash_account = Cashup._get_config_record(
            'transport_module.cash_account_id', 'account.account',
            _('The Cash / Undeposited Funds account'))

        lines = []
        company_currency = self.company_id.currency_id
        total_debit = 0.0
        for line in self.line_ids:
            account = line.expense_type_id.account_id
            if not account:
                raise UserError(_(
                    'Expense type "%s" has no expense account configured.'
                ) % line.expense_type_id.name)
            label = line.description or line.expense_type_id.name
            if line.reference:
                label = '%s (%s)' % (label, line.reference)
            company_amount = company_currency.round(
                self._to_company_amount(line.amount))
            total_debit += company_amount
            lines.append((0, 0, {
                'account_id': account.id,
                'name': label,
                'debit': company_amount,
                'credit': 0.0,
                'currency_id': self.currency_id.id,
                'amount_currency': line.amount,
            }))
        # Credit side takes the exact sum of the rounded debits so
        # foreign-currency services always balance.
        lines.append((0, 0, {
            'account_id': cash_account.id,
            'name': _('%s – service payment') % self.name,
            'debit': 0.0,
            'credit': company_currency.round(total_debit),
            'currency_id': self.currency_id.id,
            'amount_currency': -self.total_cost,
        }))

        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date_returned or self.date_sent,
            'ref': '%s / %s / %s' % (
                self.name, self.vehicle_id.registration, self.description),
            'line_ids': lines,
        }


class TransportVehicleServiceLine(models.Model):
    _name = 'transport.vehicle.service.line'
    _description = 'Vehicle Service Expense Line'

    service_id = fields.Many2one('transport.vehicle.service',
                                 string='Service', required=True,
                                 ondelete='cascade')
    expense_type_id = fields.Many2one('transport.expense.type',
                                      string='Expense Type', required=True)
    description = fields.Char(string='Description')
    reference = fields.Char(string='Invoice / Reference')
    currency_id = fields.Many2one(related='service_id.currency_id')
    amount = fields.Monetary(string='Amount', required=True)

    _amount_positive = models.Constraint(
        'CHECK(amount >= 0)',
        'Service expense amount cannot be negative.',
    )
