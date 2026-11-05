# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FuelPrice(models.Model):
    _name = 'fuel.price'
    _description = 'Pump Price'
    _order = 'product_id, valid_from desc, site_id'
    _rec_names_search = ['product_id', 'site_id']

    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('is_fuel_grade', '=', True)]", ondelete='cascade')
    site_id = fields.Many2one(
        'fuel.site', string='Site', ondelete='cascade',
        help='Leave empty to price every site. A price set on one site overrides '
             'the all-sites price for that site.')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', string='Currency', required=True,
        default=lambda self: self._default_currency())
    price = fields.Monetary(
        string='Pump Price', required=True, currency_field='currency_id',
        help='Price per litre at the pump, including VAT. This is the gazetted '
             'price the board shows, not a cost.')
    valid_from = fields.Datetime(
        string='Valid From', required=True, default=fields.Datetime.now,
        help='The moment the board changed. Sales before this keep the previous price.')
    price_status = fields.Selection(
        [('current', 'Current'), ('scheduled', 'Scheduled'), ('superseded', 'Superseded')],
        string='Status', compute='_compute_price_status')
    note = fields.Char(string='Note', help='Why it moved, e.g. the ZERA circular number.')

    _price_positive = models.Constraint(
        'CHECK(price > 0)',
        'A pump price must be greater than zero.',
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

    @api.depends('product_id', 'site_id', 'valid_from', 'price')
    def _compute_display_name(self):
        for rec in self:
            where = rec.site_id.code or _('All sites')
            when = fields.Datetime.to_string(rec.valid_from) or ''
            rec.display_name = '%s @ %s %s (%s)' % (
                rec.product_id.name or '', rec.price, where, when)

    @api.depends('product_id', 'site_id', 'valid_from')
    def _compute_price_status(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.product_id or not rec.valid_from:
                rec.price_status = 'scheduled'
                continue
            if rec.valid_from > now:
                rec.price_status = 'scheduled'
                continue
            effective = self._get_price(rec.site_id, rec.product_id, now)
            rec.price_status = 'current' if effective == rec else 'superseded'

    @api.constrains('product_id', 'site_id', 'valid_from', 'company_id')
    def _check_no_duplicate(self):
        """Two prices starting at the same instant for the same thing is ambiguous."""
        for rec in self:
            duplicate = self.search_count([
                ('id', '!=', rec.id),
                ('product_id', '=', rec.product_id.id),
                ('site_id', '=', rec.site_id.id),
                ('valid_from', '=', rec.valid_from),
                ('company_id', '=', rec.company_id.id),
            ])
            if duplicate:
                raise ValidationError(_(
                    'There is already a price for %(product)s at %(site)s starting '
                    '%(when)s. Change the time, or edit the existing price.',
                    product=rec.product_id.display_name,
                    site=rec.site_id.display_name or _('all sites'),
                    when=rec.valid_from))

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    @api.model
    def _get_price(self, site, product, when=None):
        """The price record in force for this site and product at that moment.

        A price carrying a site beats an all-sites price, whatever their dates:
        an override stays in place until it is itself replaced. Returns an empty
        recordset when nothing has been priced yet.
        """
        when = when or fields.Datetime.now()
        base = [
            ('product_id', '=', product.id),
            ('valid_from', '<=', when),
            ('company_id', '=', (site.company_id or self.env.company).id),
        ]
        if site:
            specific = self.search(
                base + [('site_id', '=', site.id)], order='valid_from desc', limit=1)
            if specific:
                return specific
        return self.search(
            base + [('site_id', '=', False)], order='valid_from desc', limit=1)

    @api.model
    def _get_price_value(self, site, product, when=None):
        """The price per litre, or an error naming what has not been priced."""
        record = self._get_price(site, product, when)
        if not record:
            raise UserError(_(
                'No pump price has been set for %(product)s at %(site)s as at '
                '%(when)s. Add one under Operations, Pump Prices.',
                product=product.display_name,
                site=site.display_name or _('any site'),
                when=when or fields.Datetime.now()))
        return record.price

    @api.model
    def _get_price_periods(self, site, product, start, end):
        """Split a window into the periods each price covers.

        Returns a list of (period_start, period_end, price_record), oldest first.
        A shift that straddles a price change gets one entry either side, which
        is what the forecourt actually sold at. Periods before the first price
        ever set are skipped rather than guessed.
        """
        if end <= start:
            return []
        domain = [
            ('product_id', '=', product.id),
            ('valid_from', '>', start),
            ('valid_from', '<', end),
            ('company_id', '=', (site.company_id or self.env.company).id),
            '|', ('site_id', '=', site.id if site else False), ('site_id', '=', False),
        ]
        changes = self.search(domain, order='valid_from')
        boundaries = [start] + sorted(set(changes.mapped('valid_from'))) + [end]
        periods = []
        for index in range(len(boundaries) - 1):
            period_start, period_end = boundaries[index], boundaries[index + 1]
            if period_end <= period_start:
                continue
            record = self._get_price(site, product, period_start)
            if not record:
                continue
            if periods and periods[-1][2] == record:
                # The change did not actually alter the effective price here.
                periods[-1] = (periods[-1][0], period_end, record)
            else:
                periods.append((period_start, period_end, record))
        return periods


class FuelSitePriceMixin(models.Model):
    _inherit = 'fuel.site'

    current_price_ids = fields.Many2many(
        'fuel.price', string='Current Prices', compute='_compute_current_price_ids')

    def _compute_current_price_ids(self):
        now = fields.Datetime.now()
        price_model = self.env['fuel.price']
        for site in self:
            products = site.tank_ids.product_id
            prices = price_model.browse()
            for product in products:
                prices |= price_model._get_price(site, product, now)
            site.current_price_ids = prices
