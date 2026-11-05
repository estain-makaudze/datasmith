# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class FuelShift(models.Model):
    _name = 'fuel.shift'
    _description = 'Forecourt Shift'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_datetime desc, id desc'
    _rec_names_search = ['name', 'site_id']

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True, default='New')
    site_id = fields.Many2one(
        'fuel.site', string='Site', required=True, tracking=True,
        ondelete='restrict')
    company_id = fields.Many2one(related='site_id.company_id', store=True)
    date = fields.Date(
        string='Business Day', required=True, default=fields.Date.context_today,
        tracking=True,
        help='The trading day this shift belongs to. A night shift ending after '
             'midnight still belongs to the day it started.')
    shift_label = fields.Selection(
        [('1', 'Shift 1'), ('2', 'Shift 2'), ('3', 'Shift 3')],
        string='Shift', required=True, default='1', tracking=True)
    start_datetime = fields.Datetime(
        string='Started', required=True, default=fields.Datetime.now, tracking=True)
    end_datetime = fields.Datetime(string='Ended', tracking=True)
    supervisor_id = fields.Many2one(
        'fuel.attendant', string='Supervisor', tracking=True,
        domain="[('site_id', '=', site_id), ('is_supervisor', '=', True)]",
        help='The person who dipped the tanks and counted the drawer.')
    user_id = fields.Many2one(
        'res.users', string='Captured By', default=lambda self: self.env.user,
        readonly=True)
    state = fields.Selection(
        [('draft', 'Draft'),
         ('open', 'Open'),
         ('closed', 'Closed'),
         ('confirmed', 'Confirmed'),
         ('posted', 'Posted'),
         ('cancelled', 'Cancelled')],
        string='Status', default='draft', required=True, tracking=True, copy=False)
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self._default_currency(),
        help='Currency the shift is summarised in. Tender may be taken in others.')
    note = fields.Text(string='Notes')

    move_id = fields.Many2one(
        'account.move', string='Journal Entry', readonly=True, copy=False)
    move_state = fields.Selection(related='move_id.state')

    nozzle_line_ids = fields.One2many(
        'fuel.shift.nozzle.line', 'shift_id', string='Nozzle Readings', copy=False)
    tank_line_ids = fields.One2many(
        'fuel.shift.tank.line', 'shift_id', string='Tank Dips', copy=False)
    tender_line_ids = fields.One2many(
        'fuel.shift.tender.line', 'shift_id', string='Tender', copy=False)
    attendant_line_ids = fields.One2many(
        'fuel.shift.attendant.line', 'shift_id', string='Per Attendant', copy=False,
        readonly=True)

    total_litres = fields.Float(
        string='Litres Sold', compute='_compute_totals', store=True, digits=(16, 2))
    total_test_litres = fields.Float(
        string='Test Litres', compute='_compute_totals', store=True, digits=(16, 2))
    total_expected = fields.Monetary(
        string='Expected Takings', compute='_compute_totals', store=True)
    total_declared = fields.Monetary(
        string='Declared', compute='_compute_totals', store=True)
    total_shortage = fields.Monetary(
        string='Cash Variance', compute='_compute_totals', store=True,
        help='Expected takings less everything declared. Positive means money is missing.')
    total_wet_variance = fields.Float(
        string='Wet Stock Variance (l)', compute='_compute_totals', store=True,
        digits=(16, 2))
    has_tolerance_breach = fields.Boolean(
        string='Over Tolerance', compute='_compute_totals', store=True)
    dips_missing = fields.Boolean(
        string='Not Dipped', compute='_compute_totals', store=True,
        help='No closing dip was taken, so wet stock cannot be reconciled for this shift.')
    price_change_warning = fields.Char(
        string='Price Warning', compute='_compute_price_change_warning')

    _name_uniq = models.Constraint(
        'UNIQUE(name, company_id)',
        'That shift reference already exists.',
    )
    _shift_slot_uniq = models.Constraint(
        'UNIQUE(site_id, date, shift_label)',
        'That shift has already been captured for this site and day.',
    )

    @api.model
    def _default_currency(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'fuel_module.default_currency_id')
        if param:
            currency = self.env['res.currency'].browse(int(param))
            if currency.exists():
                return currency.id
        return self.env.company.currency_id.id

    @api.depends('name', 'site_id', 'date', 'shift_label')
    def _compute_display_name(self):
        for shift in self:
            site = shift.site_id.code or shift.site_id.name or ''
            label = dict(self._fields['shift_label'].selection).get(shift.shift_label, '')
            shift.display_name = '%s %s %s %s' % (shift.name, site, shift.date or '', label)

    @api.depends('nozzle_line_ids.litres_sold', 'nozzle_line_ids.test_litres',
                 'nozzle_line_ids.amount_expected', 'tender_line_ids.company_amount',
                 'tank_line_ids.variance_litres', 'tank_line_ids.over_tolerance',
                 'tank_line_ids.closing_dip_mm', 'tank_line_ids.closing_dipped')
    def _compute_totals(self):
        for shift in self:
            shift.total_litres = sum(shift.nozzle_line_ids.mapped('litres_sold'))
            shift.total_test_litres = sum(shift.nozzle_line_ids.mapped('test_litres'))
            shift.total_expected = sum(shift.nozzle_line_ids.mapped('amount_expected'))
            shift.total_declared = sum(shift.tender_line_ids.mapped('company_amount'))
            shift.total_shortage = shift.total_expected - shift.total_declared
            dipped = shift.tank_line_ids.filtered('closing_dipped')
            shift.total_wet_variance = sum(dipped.mapped('variance_litres'))
            shift.has_tolerance_breach = any(dipped.mapped('over_tolerance'))
            shift.dips_missing = bool(shift.tank_line_ids) and not dipped

    @api.depends('site_id', 'start_datetime', 'end_datetime', 'nozzle_line_ids')
    def _compute_price_change_warning(self):
        """Warn when the board moved mid-shift; the split arrives in a later release."""
        for shift in self:
            warning = False
            if shift.site_id and shift.start_datetime and shift.end_datetime:
                products = shift.nozzle_line_ids.mapped('product_id')
                changed = []
                for product in products:
                    periods = self.env['fuel.price']._get_price_periods(
                        shift.site_id, product, shift.start_datetime, shift.end_datetime)
                    if len(periods) > 1:
                        changed.append(product.display_name)
                if changed:
                    warning = _(
                        'The pump price for %s changed during this shift. Expected '
                        'takings use the price at the start. Split the shift at the '
                        'change to price it exactly.') % ', '.join(changed)
            shift.price_change_warning = warning

    # ------------------------------------------------------------------
    # Defaults and prefilling
    # ------------------------------------------------------------------

    @api.onchange('site_id')
    def _onchange_site_id(self):
        """Lay out the sheet: a row per nozzle and a row per tank, opened from
        the last shift's closing readings so nothing has to be retyped."""
        self.ensure_one()
        if not self.site_id:
            self.nozzle_line_ids = [(5, 0, 0)]
            self.tank_line_ids = [(5, 0, 0)]
            return
        if self.supervisor_id and self.supervisor_id.site_id != self.site_id:
            self.supervisor_id = False
        previous = self._previous_shift()
        nozzle_vals = []
        for nozzle in self.site_id.pump_ids.nozzle_ids.sorted(
                lambda n: (n.pump_id.sequence, n.pump_id.name, n.sequence, n.name)):
            nozzle_vals.append((0, 0, {
                'nozzle_id': nozzle.id,
                'opening_totaliser': nozzle.current_totaliser,
            }))
        tank_vals = []
        for tank in self.site_id.tank_ids.sorted(lambda t: (t.sequence, t.name)):
            opening_dip = 0.0
            if previous:
                last = previous.tank_line_ids.filtered(lambda l: l.tank_id == tank)[:1]
                opening_dip = last.closing_dip_mm if last else 0.0
            tank_vals.append((0, 0, {
                'tank_id': tank.id,
                'opening_dip_mm': opening_dip,
            }))
        self.nozzle_line_ids = [(5, 0, 0)] + nozzle_vals
        self.tank_line_ids = [(5, 0, 0)] + tank_vals

    def _previous_shift(self):
        """The last shift at this site that is not a draft or a cancellation."""
        self.ensure_one()
        if not self.site_id:
            return self.browse()
        domain = [
            ('site_id', '=', self.site_id.id),
            ('state', 'not in', ('draft', 'cancelled')),
        ]
        if self.start_datetime:
            domain.append(('start_datetime', '<', self.start_datetime))
        if isinstance(self.id, int):
            domain.append(('id', '!=', self.id))
        return self.search(domain, order='start_datetime desc', limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('fuel.shift') or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains('start_datetime', 'end_datetime')
    def _check_times(self):
        for shift in self:
            if shift.end_datetime and shift.end_datetime <= shift.start_datetime:
                raise ValidationError(_(
                    'Shift %s ends before it starts.') % shift.name)

    @api.constrains('supervisor_id', 'site_id')
    def _check_supervisor_site(self):
        for shift in self:
            if shift.supervisor_id and shift.supervisor_id.site_id != shift.site_id:
                raise ValidationError(_(
                    '%(person)s is not posted to %(site)s.',
                    person=shift.supervisor_id.name, site=shift.site_id.display_name))

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def action_open(self):
        """Lock the opening readings. After this they cannot be edited."""
        for shift in self:
            if shift.state != 'draft':
                raise UserError(_('Only a draft shift can be opened.'))
            if not shift.nozzle_line_ids:
                raise UserError(_(
                    'Shift %s has no nozzle readings. Pick the site again to lay out '
                    'the sheet, or register nozzles on the site first.') % shift.name)
            shift.nozzle_line_ids._check_opening_against_nozzle()
            shift.state = 'open'
            shift.message_post(body=_('Opening readings locked.'))

    def action_close(self):
        """Take the closing readings, work out both variances, name the shortfalls."""
        for shift in self:
            if shift.state != 'open':
                raise UserError(_('Only an open shift can be closed.'))
            missing = shift.nozzle_line_ids.filtered(lambda l: not l.closing_entered)
            if missing:
                raise UserError(_(
                    'These nozzles have no closing reading: %s.'
                ) % ', '.join(missing.mapped('nozzle_id.display_name')))
            shift.nozzle_line_ids._price_error_if_unpriced()
            if not shift.end_datetime:
                shift.end_datetime = fields.Datetime.now()
            shift._rebuild_attendant_lines()
            shift.state = 'closed'
            shift.message_post(body=_(
                'Closed. %(litres)s litres sold, wet stock variance %(wet)s l, '
                'cash variance %(cash)s.',
                litres=round(shift.total_litres, 2),
                wet=round(shift.total_wet_variance, 2),
                cash=round(shift.total_shortage, 2)))

    def action_confirm(self):
        """A supervisor signs the sheet off and the nozzle counters move on."""
        for shift in self:
            if shift.state != 'closed':
                raise UserError(_('Only a closed shift can be confirmed.'))
            if not self.env.user.has_group('fuel_module.group_fuel_supervisor'):
                raise UserError(_(
                    'Only a supervisor or manager can confirm a shift.'))
            if not shift.supervisor_id:
                raise UserError(_(
                    'Name the supervisor who dipped the tanks before confirming.'))
            for line in shift.nozzle_line_ids:
                line.nozzle_id.current_totaliser = line.closing_totaliser
            shift.state = 'confirmed'
            shift.message_post(body=_('Confirmed by %s.') % shift.supervisor_id.name)

    def action_cancel(self):
        for shift in self:
            if shift.state == 'posted':
                raise UserError(_(
                    'Shift %s is posted to Accounting and cannot be cancelled.') % shift.name)
            shift.state = 'cancelled'

    def action_reset_to_draft(self):
        for shift in self:
            if shift.state == 'posted':
                raise UserError(_(
                    'Shift %s is posted to Accounting. Reverse the entry first.') % shift.name)
            shift.state = 'draft'


    def action_post(self):
        """One balanced entry per shift. Never silent, never twice."""
        for shift in self:
            if shift.state != 'confirmed':
                raise UserError(_(
                    'Confirm shift %s before posting it to Accounting.') % shift.name)
            if shift.move_id:
                raise UserError(_(
                    'Shift %(name)s is already posted as %(move)s.',
                    name=shift.name, move=shift.move_id.name))
            move = self.env['account.move'].create(shift._prepare_move_vals())
            move._post()
            shift.move_id = move
            shift.state = 'posted'
            shift.message_post(body=_('Posted to Accounting as %s.') % move.name)

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
        """Fetch a configured journal or account, naming what is missing."""
        value = self.env['ir.config_parameter'].sudo().get_param(param)
        record = self.env[model].browse(int(value)) if value else self.env[model]
        if not record.exists():
            raise UserError(_(
                '%s is not configured. Set it under Fuel Stations, Configuration, '
                'Settings.') % label)
        return record

    def _get_config_optional(self, param, model):
        value = self.env['ir.config_parameter'].sudo().get_param(param)
        record = self.env[model].browse(int(value)) if value else self.env[model]
        return record if record.exists() else self.env[model]

    def _split_tax(self, gross):
        """Split a VAT-inclusive gross into net and VAT, the way the board price works.

        Returns (net, vat, tax). With no tax configured the whole amount is net.
        """
        self.ensure_one()
        tax = self._get_config_optional('fuel_module.tax_id', 'account.tax')
        if not tax:
            return gross, 0.0, tax
        if tax.amount_type != 'percent':
            raise UserError(_(
                'The configured Output VAT must be a percentage tax. %s is not.'
            ) % tax.display_name)
        inclusive = self.env['ir.config_parameter'].sudo().get_param(
            'fuel_module.price_tax_included')
        inclusive = inclusive not in ('False', 'false', '0', False, None) or inclusive is None
        rate = tax.amount / 100.0
        currency = self.currency_id
        if inclusive:
            net = currency.round(gross / (1.0 + rate)) if rate else gross
            vat = currency.round(gross - net)
        else:
            net = gross
            vat = currency.round(gross * rate)
        return net, vat, tax

    def _prepare_move_vals(self):
        self.ensure_one()
        journal = self._get_config_record(
            'fuel_module.journal_id', 'account.journal', _('The Forecourt journal'))
        currency = self.currency_id
        company_currency = self.company_id.currency_id
        lines = []
        debit_total = 0.0
        credit_total = 0.0

        def add(account, label, debit=0.0, credit=0.0, partner=None, extra=None):
            nonlocal debit_total, credit_total
            debit = company_currency.round(debit)
            credit = company_currency.round(credit)
            if not debit and not credit:
                return
            debit_total += debit
            credit_total += credit
            vals = {
                'account_id': account.id,
                'name': label,
                'partner_id': partner.id if partner else False,
                'debit': debit,
                'credit': credit,
            }
            if extra:
                vals.update(extra)
            lines.append((0, 0, vals))

        # --- what came in ------------------------------------------------
        for method in self.tender_line_ids.mapped('method_id'):
            method_lines = self.tender_line_ids.filtered(lambda l, m=method: l.method_id == m)
            amount = sum(method_lines.mapped('company_amount'))
            if not method.account_id:
                raise UserError(_(
                    'Payment method %s has no clearing account. Set one under '
                    'Configuration, Payment Methods.') % method.display_name)
            add(method.account_id, _('%(ref)s - %(method)s',
                                     ref=self.name, method=method.name), debit=amount)

        # --- what did not, and whose it was -------------------------------
        shortage_account = None
        for line in self.attendant_line_ids:
            if currency.is_zero(line.amount_shortage):
                continue
            if shortage_account is None:
                shortage_account = self._get_config_record(
                    'fuel_module.shortage_account_id', 'account.account',
                    _('The Attendant Shortage account'))
            label = _('%(ref)s - shortage, %(who)s',
                      ref=self.name, who=line.attendant_id.name)
            if line.amount_shortage > 0:
                add(shortage_account, label, debit=line.amount_shortage,
                    partner=line.attendant_id.partner_id)
            else:
                add(shortage_account, _('%(ref)s - overage, %(who)s',
                                        ref=self.name, who=line.attendant_id.name),
                    credit=-line.amount_shortage, partner=line.attendant_id.partner_id)

        # --- the sale, split out of the VAT-inclusive board price ----------
        sales_default = self._get_config_optional(
            'fuel_module.sales_account_id', 'account.account')
        by_product = {}
        for line in self.nozzle_line_ids:
            if line.amount_expected:
                by_product.setdefault(line.product_id, 0.0)
                by_product[line.product_id] += line.amount_expected
        vat_total = 0.0
        tax = None
        for product, gross in by_product.items():
            net, vat, tax = self._split_tax(gross)
            income = sales_default or product.property_account_income_id or \
                product.categ_id.property_account_income_categ_id
            if not income:
                raise UserError(_(
                    'No income account for %s. Set a Fuel Sales account in Settings, '
                    'or an income account on the product.') % product.display_name)
            extra = {}
            if tax:
                base_tags = tax.invoice_repartition_line_ids.filtered(
                    lambda r: r.repartition_type == 'base').tag_ids
                extra = {'tax_ids': [(6, 0, tax.ids)]}
                if base_tags:
                    extra['tax_tag_ids'] = [(6, 0, base_tags.ids)]
            add(income, _('%(ref)s - %(product)s sales',
                          ref=self.name, product=product.display_name),
                credit=net, extra=extra)
            vat_total += vat
        if tax and not currency.is_zero(vat_total):
            rep_tax = tax.invoice_repartition_line_ids.filtered(
                lambda r: r.repartition_type == 'tax')[:1]
            vat_account = rep_tax.account_id
            if not vat_account:
                raise UserError(_(
                    'The Output VAT tax %s has no account on its distribution, so '
                    'the VAT cannot be posted.') % tax.display_name)
            add(vat_account, _('%(ref)s - output VAT', ref=self.name),
                credit=vat_total,
                extra={'tax_repartition_line_id': rep_tax.id,
                       'tax_tag_ids': [(6, 0, rep_tax.tag_ids.ids)]} if rep_tax.tag_ids
                else {'tax_repartition_line_id': rep_tax.id})

        # --- what left the ground -----------------------------------------
        stock_account = cogs_account = loss_account = None
        for tank_line in self.tank_line_ids:
            cost = tank_line.tank_id.average_cost
            if not cost:
                continue
            if stock_account is None:
                stock_account = self._get_config_record(
                    'fuel_module.stock_account_id', 'account.account',
                    _('The Fuel Stock account'))
                cogs_account = self._get_config_record(
                    'fuel_module.cogs_account_id', 'account.account',
                    _('The Cost of Sales account'))
            sold_value = company_currency.round(tank_line.sold_litres * cost)
            add(cogs_account, _('%(ref)s - cost of %(tank)s',
                                ref=self.name, tank=tank_line.tank_id.name),
                debit=sold_value)
            add(stock_account, _('%(ref)s - %(tank)s stock out',
                                 ref=self.name, tank=tank_line.tank_id.name),
                credit=sold_value)
            if tank_line.closing_dipped and not currency.is_zero(tank_line.variance_litres):
                if loss_account is None:
                    loss_account = self._get_config_record(
                        'fuel_module.stock_loss_account_id', 'account.account',
                        _('The Wet Stock Loss account'))
                variance_value = company_currency.round(
                    abs(tank_line.variance_litres) * cost)
                label = _('%(ref)s - %(tank)s wet stock variance %(litres)s l',
                          ref=self.name, tank=tank_line.tank_id.name,
                          litres=round(tank_line.variance_litres, 2))
                if tank_line.variance_litres < 0:
                    add(loss_account, label, debit=variance_value)
                    add(stock_account, label, credit=variance_value)
                else:
                    add(stock_account, label, debit=variance_value)
                    add(loss_account, label, credit=variance_value)

        if not lines:
            raise UserError(_(
                'Shift %s has nothing to post: no tender, no shortage and no sales.'
            ) % self.name)
        difference = company_currency.round(debit_total - credit_total)
        if not company_currency.is_zero(difference):
            raise UserError(_(
                'Shift %(name)s does not balance: debits %(debit)s against credits '
                '%(credit)s. This is a rounding or configuration problem, not a '
                'forecourt one.',
                name=self.name, debit=debit_total, credit=credit_total))
        return {
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': '%s / %s' % (self.name, self.site_id.display_name),
            'line_ids': lines,
        }

    def _rebuild_attendant_lines(self):
        """One row per attendant: what their nozzles owed, what they handed over."""
        self.ensure_one()
        self.attendant_line_ids.unlink()
        expected = {}
        declared = {}
        for line in self.nozzle_line_ids:
            if line.attendant_id:
                expected.setdefault(line.attendant_id, 0.0)
                expected[line.attendant_id] += line.amount_expected
        for line in self.tender_line_ids:
            if line.attendant_id:
                declared.setdefault(line.attendant_id, 0.0)
                declared[line.attendant_id] += line.company_amount
        for attendant in set(expected) | set(declared):
            self.env['fuel.shift.attendant.line'].create({
                'shift_id': self.id,
                'attendant_id': attendant.id,
                'amount_expected': expected.get(attendant, 0.0),
                'amount_declared': declared.get(attendant, 0.0),
            })

    @api.ondelete(at_uninstall=False)
    def _unlink_except_posted(self):
        for shift in self:
            if shift.state == 'posted':
                raise UserError(_(
                    'Shift %s is posted to Accounting and cannot be deleted.') % shift.name)

    def action_view_unassigned(self):
        """Tender or readings with nobody's name on them are the usual mistake."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Readings with no attendant'),
            'res_model': 'fuel.shift.nozzle.line',
            'view_mode': 'list',
            'domain': [('shift_id', '=', self.id), ('attendant_id', '=', False)],
        }


class FuelShiftNozzleLine(models.Model):
    _name = 'fuel.shift.nozzle.line'
    _description = 'Shift Nozzle Reading'
    _order = 'shift_id, nozzle_id'

    shift_id = fields.Many2one(
        'fuel.shift', string='Shift', required=True, ondelete='cascade', index=True)
    state = fields.Selection(related='shift_id.state', store=True)
    site_id = fields.Many2one(related='shift_id.site_id', store=True)
    currency_id = fields.Many2one(related='shift_id.currency_id')
    nozzle_id = fields.Many2one(
        'fuel.nozzle', string='Nozzle', required=True, ondelete='restrict')
    tank_id = fields.Many2one(related='nozzle_id.tank_id', store=True)
    product_id = fields.Many2one(related='nozzle_id.product_id', store=True)
    attendant_id = fields.Many2one(
        'fuel.attendant', string='Attendant',
        domain="[('site_id', '=', site_id)]",
        help='Whose takings these litres are. A shortage lands on this name.')
    opening_totaliser = fields.Float(string='Opening', required=True, digits=(16, 2))
    closing_totaliser = fields.Float(string='Closing', digits=(16, 2))
    closing_entered = fields.Boolean(
        string='Closing Entered', compute='_compute_closing_entered', store=True)
    test_litres = fields.Float(
        string='Test Litres', digits=(16, 2),
        help='Pumped into a measure to check calibration and poured back. '
             'On the meter, never sold.')
    litres_sold = fields.Float(
        string='Litres Sold', compute='_compute_litres_sold', store=True, digits=(16, 2))
    price_unit = fields.Monetary(
        string='Price', compute='_compute_amount', store=True, currency_field='currency_id')
    amount_expected = fields.Monetary(
        string='Expected', compute='_compute_amount', store=True,
        currency_field='currency_id')

    _closing_not_below_opening = models.Constraint(
        'CHECK(closing_totaliser = 0 OR closing_totaliser >= opening_totaliser)',
        'A closing totaliser cannot be lower than the opening one. Meters only count up.',
    )
    _test_litres_positive = models.Constraint(
        'CHECK(test_litres >= 0)',
        'Test litres cannot be negative.',
    )

    @api.depends('closing_totaliser')
    def _compute_closing_entered(self):
        for line in self:
            line.closing_entered = not float_is_zero(
                line.closing_totaliser, precision_digits=2)

    @api.depends('opening_totaliser', 'closing_totaliser', 'test_litres', 'closing_entered')
    def _compute_litres_sold(self):
        for line in self:
            if not line.closing_entered:
                line.litres_sold = 0.0
                continue
            throughput = line.closing_totaliser - line.opening_totaliser
            line.litres_sold = max(throughput - line.test_litres, 0.0)

    @api.depends('litres_sold', 'product_id', 'shift_id.start_datetime', 'site_id')
    def _compute_amount(self):
        price_model = self.env['fuel.price']
        for line in self:
            price = 0.0
            if line.product_id and line.site_id and line.shift_id.start_datetime:
                record = price_model._get_price(
                    line.site_id, line.product_id, line.shift_id.start_datetime)
                price = record.price if record else 0.0
            line.price_unit = price
            line.amount_expected = price * line.litres_sold

    @api.constrains('closing_totaliser', 'opening_totaliser', 'test_litres')
    def _check_test_litres(self):
        for line in self:
            if not line.closing_entered:
                continue
            throughput = line.closing_totaliser - line.opening_totaliser
            if float_compare(line.test_litres, throughput, precision_digits=2) > 0:
                raise ValidationError(_(
                    'Nozzle %(nozzle)s: %(test)s test litres is more than the '
                    '%(through)s litres the meter moved.',
                    nozzle=line.nozzle_id.display_name,
                    test=line.test_litres, through=throughput))

    def _check_opening_against_nozzle(self):
        """The sheet must start where the last one finished, or the gap is a loss."""
        for line in self:
            expected = line.nozzle_id.current_totaliser
            if float_compare(line.opening_totaliser, expected, precision_digits=2) != 0:
                line.shift_id.message_post(body=_(
                    'Opening reading on %(nozzle)s is %(given)s but the nozzle last '
                    'closed at %(expected)s. The difference of %(gap)s litres is '
                    'unaccounted for.',
                    nozzle=line.nozzle_id.display_name,
                    given=line.opening_totaliser, expected=expected,
                    gap=round(line.opening_totaliser - expected, 2)))

    def _price_error_if_unpriced(self):
        for line in self.filtered(lambda l: l.litres_sold and not l.price_unit):
            raise UserError(_(
                'No pump price covers %(product)s at %(site)s on %(when)s. '
                'Add one under Operations, Pump Prices.',
                product=line.product_id.display_name,
                site=line.site_id.display_name,
                when=line.shift_id.start_datetime))


class FuelShiftTankLine(models.Model):
    _name = 'fuel.shift.tank.line'
    _description = 'Shift Tank Dip'
    _order = 'shift_id, tank_id'

    shift_id = fields.Many2one(
        'fuel.shift', string='Shift', required=True, ondelete='cascade', index=True)
    state = fields.Selection(related='shift_id.state', store=True)
    site_id = fields.Many2one(related='shift_id.site_id', store=True)
    tank_id = fields.Many2one(
        'fuel.tank', string='Tank', required=True, ondelete='restrict')
    product_id = fields.Many2one(related='tank_id.product_id', store=True)
    opening_dip_mm = fields.Float(string='Opening Dip (mm)', digits=(16, 1))
    opening_litres = fields.Float(
        string='Opening (l)', compute='_compute_litres', store=True, digits=(16, 2))
    closing_dip_mm = fields.Float(string='Closing Dip (mm)', digits=(16, 1))
    closing_litres = fields.Float(
        string='Closing (l)', compute='_compute_litres', store=True, digits=(16, 2))
    closing_dipped = fields.Boolean(
        string='Dipped', compute='_compute_litres', store=True,
        help='Cleared when no closing dip was taken on this shift.')
    water_dip_mm = fields.Float(
        string='Water (mm)', digits=(16, 1),
        help='Water found with the paste. Anything above zero is a problem, '
             'not a variance.')
    delivered_litres = fields.Float(
        string='Delivered In (l)', digits=(16, 2),
        help='Litres decanted into this tank during the shift. Linked to the '
             'delivery document in a later release.')
    sold_litres = fields.Float(
        string='Sold (l)', compute='_compute_sold', store=True, digits=(16, 2),
        help='From the nozzles that draw on this tank, net of test litres.')
    book_closing_litres = fields.Float(
        string='Book Closing (l)', compute='_compute_variance', store=True, digits=(16, 2))
    variance_litres = fields.Float(
        string='Variance (l)', compute='_compute_variance', store=True, digits=(16, 2),
        help='Dip less book stock. Negative means fuel is missing.')
    variance_percent = fields.Float(
        string='Variance (%)', compute='_compute_variance', store=True, digits=(16, 3))
    over_tolerance = fields.Boolean(
        string='Over Tolerance', compute='_compute_variance', store=True)

    @api.depends('opening_dip_mm', 'closing_dip_mm', 'tank_id')
    def _compute_litres(self):
        for line in self:
            tank = line.tank_id
            has_chart = bool(tank.chart_line_ids)
            line.opening_litres = (
                tank.dip_to_litres(line.opening_dip_mm) if has_chart else 0.0)
            dipped = not float_is_zero(line.closing_dip_mm, precision_digits=1)
            line.closing_dipped = dipped
            line.closing_litres = (
                tank.dip_to_litres(line.closing_dip_mm) if (has_chart and dipped) else 0.0)

    @api.depends('shift_id.nozzle_line_ids.litres_sold',
                 'shift_id.nozzle_line_ids.tank_id', 'tank_id')
    def _compute_sold(self):
        for line in self:
            lines = line.shift_id.nozzle_line_ids.filtered(
                lambda l, t=line.tank_id: l.tank_id == t)
            line.sold_litres = sum(lines.mapped('litres_sold'))

    @api.depends('opening_litres', 'closing_litres', 'closing_dipped',
                 'delivered_litres', 'sold_litres', 'site_id.tolerance_percent')
    def _compute_variance(self):
        for line in self:
            book = line.opening_litres + line.delivered_litres - line.sold_litres
            line.book_closing_litres = book
            if not line.closing_dipped:
                line.variance_litres = 0.0
                line.variance_percent = 0.0
                line.over_tolerance = False
                continue
            variance = line.closing_litres - book
            line.variance_litres = variance
            throughput = line.sold_litres
            line.variance_percent = (
                (variance / throughput * 100.0) if throughput else 0.0)
            tolerance = line.site_id.tolerance_percent or 0.0
            line.over_tolerance = bool(
                throughput and abs(line.variance_percent) > tolerance)


class FuelShiftTenderLine(models.Model):
    _name = 'fuel.shift.tender.line'
    _description = 'Shift Tender'
    _order = 'shift_id, method_id, id'

    shift_id = fields.Many2one(
        'fuel.shift', string='Shift', required=True, ondelete='cascade', index=True)
    state = fields.Selection(related='shift_id.state', store=True)
    site_id = fields.Many2one(related='shift_id.site_id', store=True)
    company_id = fields.Many2one(related='shift_id.company_id', store=True)
    company_currency_id = fields.Many2one(related='shift_id.currency_id')
    attendant_id = fields.Many2one(
        'fuel.attendant', string='Attendant', domain="[('site_id', '=', site_id)]")
    method_id = fields.Many2one(
        'fuel.payment.method', string='Method', required=True, ondelete='restrict')
    kind = fields.Selection(related='method_id.kind', store=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self._default_tender_currency())
    amount = fields.Monetary(
        string='Tendered', required=True, currency_field='currency_id',
        help='The amount as it was handed over, in the currency it was handed over in.')
    rate = fields.Float(
        string='Rate Used', digits=(16, 6), default=1.0,
        help='Units of shift currency for one unit of the tendered currency. '
             'The rate the supervisor actually applied, not the bank rate.')
    company_amount = fields.Monetary(
        string='In Shift Currency', compute='_compute_company_amount', store=True,
        currency_field='company_currency_id')
    reference = fields.Char(
        string='Reference', help='Mobile money or swipe reference, to verify later.')

    _amount_positive = models.Constraint(
        'CHECK(amount >= 0)',
        'A tendered amount cannot be negative.',
    )
    _rate_positive = models.Constraint(
        'CHECK(rate > 0)',
        'The rate must be greater than zero.',
    )

    @api.model
    def _default_tender_currency(self):
        return self.env.company.currency_id.id

    @api.depends('amount', 'rate')
    def _compute_company_amount(self):
        for line in self:
            line.company_amount = line.amount * (line.rate or 1.0)

    @api.onchange('method_id')
    def _onchange_method_id(self):
        if self.method_id.currency_id:
            self.currency_id = self.method_id.currency_id
        if self.currency_id == self.shift_id.currency_id:
            self.rate = 1.0

    @api.constrains('method_id', 'reference')
    def _check_reference(self):
        for line in self:
            if line.method_id.requires_reference and not line.reference:
                raise ValidationError(_(
                    '%s needs a transaction reference so it can be verified later.'
                ) % line.method_id.display_name)


class FuelShiftAttendantLine(models.Model):
    _name = 'fuel.shift.attendant.line'
    _description = 'Shift Result per Attendant'
    _order = 'shift_id, amount_shortage desc'

    shift_id = fields.Many2one(
        'fuel.shift', string='Shift', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='shift_id.currency_id')
    attendant_id = fields.Many2one(
        'fuel.attendant', string='Attendant', required=True, ondelete='restrict')
    partner_id = fields.Many2one(related='attendant_id.partner_id', store=True)
    amount_expected = fields.Monetary(string='Expected')
    amount_declared = fields.Monetary(string='Declared')
    amount_shortage = fields.Monetary(
        string='Shortage', compute='_compute_shortage', store=True,
        help='Positive means this attendant handed over less than their nozzles owed.')

    @api.depends('amount_expected', 'amount_declared')
    def _compute_shortage(self):
        for line in self:
            line.amount_shortage = line.amount_expected - line.amount_declared
