# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class TransportLeaveType(models.Model):
    _name = 'transport.leave.type'
    _description = 'Transport Leave Type'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    paid = fields.Boolean(
        string='Paid Leave', default=True,
        help='Untick for unpaid absence: approved days of this type reduce '
             'the fixed wage pro-rata in driver payment runs.')
    requires_allocation = fields.Boolean(
        string='Requires Allocation', default=False,
        help='If ticked, a leave request needs a remaining allocation '
             'balance before it can be approved.')
    default_annual_days = fields.Float(
        string='Default Annual Days', digits=(5, 1),
        help='Days proposed when allocating this leave type to a crew member.')
    color = fields.Integer(string='Color')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)


class TransportLeaveAllocation(models.Model):
    _name = 'transport.leave.allocation'
    _description = 'Transport Leave Allocation'
    _order = 'year desc, driver_id'

    driver_id = fields.Many2one('transport.driver', string='Crew Member',
                                required=True, ondelete='cascade')
    leave_type_id = fields.Many2one('transport.leave.type', string='Leave Type',
                                    required=True)
    year = fields.Integer(string='Year', required=True,
                          default=lambda self: fields.Date.context_today(self).year)
    days_allocated = fields.Float(string='Days Allocated', digits=(5, 1),
                                  required=True)
    days_taken = fields.Float(string='Days Taken', digits=(5, 1),
                              compute='_compute_days', store=False)
    days_remaining = fields.Float(string='Days Remaining', digits=(5, 1),
                                  compute='_compute_days', store=False)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    _unique_driver_type_year = models.Constraint(
        'UNIQUE(driver_id, leave_type_id, year)',
        'This crew member already has an allocation for that leave type and year.',
    )
    _days_positive = models.Constraint(
        'CHECK(days_allocated > 0)',
        'Allocated days must be greater than zero.',
    )

    @api.onchange('leave_type_id')
    def _onchange_leave_type_id(self):
        if self.leave_type_id and not self.days_allocated:
            self.days_allocated = self.leave_type_id.default_annual_days

    def _compute_days(self):
        Leave = self.env['transport.leave']
        for allocation in self:
            taken = 0.0
            if allocation.driver_id and allocation.leave_type_id:
                leaves = Leave.search([
                    ('driver_id', '=', allocation.driver_id.id),
                    ('leave_type_id', '=', allocation.leave_type_id.id),
                    ('state', '=', 'approved'),
                    ('date_from', '>=', '%s-01-01' % allocation.year),
                    ('date_from', '<=', '%s-12-31' % allocation.year),
                ])
                taken = sum(leaves.mapped('days'))
            allocation.days_taken = taken
            allocation.days_remaining = allocation.days_allocated - taken


class TransportLeave(models.Model):
    _name = 'transport.leave'
    _description = 'Transport Leave Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False,
                       readonly=True, default='New')
    driver_id = fields.Many2one('transport.driver', string='Crew Member',
                                required=True, tracking=True)
    leave_type_id = fields.Many2one('transport.leave.type', string='Leave Type',
                                    required=True, tracking=True)
    paid = fields.Boolean(related='leave_type_id.paid', store=True,
                          string='Paid')
    date_from = fields.Date(string='From', required=True, tracking=True)
    date_to = fields.Date(string='To', required=True, tracking=True)
    days = fields.Float(string='Days', digits=(5, 1),
                        compute='_compute_days', store=True,
                        help='Working days requested — Sundays are not counted '
                             '(kombis run a six-day week).')
    reason = fields.Char(string='Reason')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('refused', 'Refused'),
    ], string='Status', default='draft', required=True, tracking=True, copy=False)
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'transport.leave') or 'New'
        return super().create(vals_list)

    @api.depends('date_from', 'date_to')
    def _compute_days(self):
        for leave in self:
            leave.days = (leave._working_days_between(
                leave.date_from, leave.date_to)
                if leave.date_from and leave.date_to else 0.0)

    @staticmethod
    def _working_days_between(date_from, date_to):
        """Days in the span excluding Sundays (six-day working week)."""
        if date_to < date_from:
            return 0.0
        days = 0
        current = date_from
        while current <= date_to:
            if current.weekday() != 6:
                days += 1
            current += timedelta(days=1)
        return float(days)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for leave in self:
            if leave.date_to < leave.date_from:
                raise ValidationError(_(
                    'The end date cannot be before the start date.'))

    @api.constrains('driver_id', 'date_from', 'date_to', 'state')
    def _check_overlap(self):
        for leave in self:
            if leave.state == 'refused':
                continue
            overlap = self.search_count([
                ('id', '!=', leave.id),
                ('driver_id', '=', leave.driver_id.id),
                ('state', 'in', ('submitted', 'approved')),
                ('date_from', '<=', leave.date_to),
                ('date_to', '>=', leave.date_from),
            ], limit=1)
            if overlap:
                raise ValidationError(_(
                    '%s already has a leave request overlapping these dates.'
                ) % leave.driver_id.full_name)

    def action_submit(self):
        for leave in self:
            if leave.state != 'draft':
                raise UserError(_('Only draft requests can be submitted.'))
            leave.state = 'submitted'

    def action_approve(self):
        for leave in self:
            if leave.state != 'submitted':
                raise UserError(_('Only submitted requests can be approved.'))
            if leave.leave_type_id.requires_allocation:
                allocation = self.env['transport.leave.allocation'].search([
                    ('driver_id', '=', leave.driver_id.id),
                    ('leave_type_id', '=', leave.leave_type_id.id),
                    ('year', '=', leave.date_from.year),
                ], limit=1)
                if not allocation:
                    raise UserError(_(
                        '%s has no %s allocation for %s.') % (
                        leave.driver_id.full_name,
                        leave.leave_type_id.name, leave.date_from.year))
                if allocation.days_remaining < leave.days:
                    raise UserError(_(
                        '%s has only %.1f day(s) of %s remaining; this '
                        'request needs %.1f.') % (
                        leave.driver_id.full_name, allocation.days_remaining,
                        leave.leave_type_id.name, leave.days))
            leave.state = 'approved'

    def action_refuse(self):
        for leave in self:
            if leave.state not in ('submitted', 'approved'):
                raise UserError(_('Only submitted or approved requests can '
                                  'be refused.'))
            leave.state = 'refused'

    def action_draft(self):
        for leave in self:
            leave.state = 'draft'
