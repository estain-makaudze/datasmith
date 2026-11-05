# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class FuelTank(models.Model):
    _name = 'fuel.tank'
    _description = 'Underground Fuel Tank'
    _order = 'site_id, sequence, name'

    name = fields.Char(string='Tank', required=True, help='As painted on the fill point, e.g. Tank 1.')
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    site_id = fields.Many2one('fuel.site', string='Site', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='site_id.company_id', store=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('is_fuel_grade', '=', True)]",
        help='The grade this tank holds. One tank holds one grade.')
    capacity_litres = fields.Float(string='Capacity (l)', required=True, digits=(16, 2))
    dead_stock_litres = fields.Float(
        string='Dead Stock (l)', digits=(16, 2),
        help='Litres below the pump suction that can never be sold.')
    safe_fill_percent = fields.Float(
        string='Safe Fill (%)', default=95.0,
        help='Fraction of capacity a delivery may fill to.')
    currency_id = fields.Many2one(related='company_id.currency_id')
    average_cost = fields.Monetary(
        string='Average Cost / l', currency_field='currency_id', digits=(16, 4),
        help='Weighted average landed cost of the fuel in this tank. Deliveries '
             'keep it up to date; set it by hand for the first shift.')
    chart_line_ids = fields.One2many(
        'fuel.tank.chart.line', 'tank_id', string='Strapping Chart')
    chart_line_count = fields.Integer(compute='_compute_chart_line_count')
    nozzle_ids = fields.One2many('fuel.nozzle', 'tank_id', string='Nozzles')

    _capacity_positive = models.Constraint(
        'CHECK(capacity_litres > 0)',
        'Tank capacity must be greater than zero.',
    )
    _dead_stock_positive = models.Constraint(
        'CHECK(dead_stock_litres >= 0)',
        'Dead stock cannot be negative.',
    )

    @api.depends('chart_line_ids')
    def _compute_chart_line_count(self):
        for tank in self:
            tank.chart_line_count = len(tank.chart_line_ids)

    @api.depends('name', 'site_id', 'product_id')
    def _compute_display_name(self):
        for tank in self:
            parts = [tank.site_id.code or tank.site_id.name, tank.name]
            if tank.product_id:
                parts.append(tank.product_id.name)
            tank.display_name = ' / '.join(p for p in parts if p)

    @api.constrains('capacity_litres', 'dead_stock_litres')
    def _check_dead_stock(self):
        for tank in self:
            if tank.dead_stock_litres >= tank.capacity_litres:
                raise ValidationError(_(
                    'Tank %s: dead stock must be less than capacity.') % tank.name)

    @api.constrains('product_id')
    def _check_product_is_fuel(self):
        """A tank holds fuel. Catching this here stops a look-alike product,
        created in passing from this form, quietly splitting prices in two."""
        for tank in self:
            if tank.product_id and not tank.product_id.is_fuel_grade:
                raise ValidationError(_(
                    '%(product)s is not marked as a fuel grade, so it cannot go in '
                    'a tank. Tick Fuel Grade on the product, or pick the grade you '
                    'already use under Configuration, Fuel Grades.',
                    product=tank.product_id.display_name))

    @api.constrains('chart_line_ids')
    def _check_chart_monotonic(self):
        """Litres must never fall as the dip rises, or the chart is unusable."""
        for tank in self:
            lines = tank.chart_line_ids.sorted('dip_mm')
            previous = None
            for line in lines:
                if previous is not None and line.litres < previous.litres:
                    raise ValidationError(_(
                        'Tank %(tank)s: the strapping chart falls from %(a)s l at '
                        '%(amm)s mm to %(b)s l at %(bmm)s mm. Litres must rise with '
                        'the dip.',
                        tank=tank.name, a=previous.litres, amm=previous.dip_mm,
                        b=line.litres, bmm=line.dip_mm))
                previous = line

    def dip_to_litres(self, dip_mm):
        """Convert a dip in millimetres to litres through this tank's chart.

        Interpolates linearly between the two chart rows either side of the
        reading. Below the first row it interpolates from an empty tank; above
        the last row it returns the last row, because the chart is the only
        truth we have about the shape of the tank.
        """
        self.ensure_one()
        lines = self.chart_line_ids.sorted('dip_mm')
        if not lines:
            raise UserError(_(
                'Tank %s has no strapping chart, so a dip cannot be converted '
                'to litres. Add the chart on the tank first.') % self.display_name)
        dip_mm = float(dip_mm or 0.0)
        if dip_mm <= 0:
            return 0.0
        first = lines[0]
        if dip_mm <= first.dip_mm:
            if not first.dip_mm:
                return first.litres
            return first.litres * (dip_mm / first.dip_mm)
        last = lines[-1]
        if dip_mm >= last.dip_mm:
            return last.litres
        previous = first
        for line in lines[1:]:
            if dip_mm <= line.dip_mm:
                span = line.dip_mm - previous.dip_mm
                if not span:
                    return line.litres
                ratio = (dip_mm - previous.dip_mm) / span
                return previous.litres + ratio * (line.litres - previous.litres)
            previous = line
        return last.litres

    def action_test_dip(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Test a Dip'),
            'res_model': 'fuel.dip.test',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_tank_id': self.id},
        }

    def action_view_chart(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Strapping Chart'),
            'res_model': 'fuel.tank.chart.line',
            'view_mode': 'list',
            'domain': [('tank_id', '=', self.id)],
            'context': {'default_tank_id': self.id},
        }


class FuelTankChartLine(models.Model):
    _name = 'fuel.tank.chart.line'
    _description = 'Tank Strapping Chart Line'
    _order = 'tank_id, dip_mm'

    tank_id = fields.Many2one('fuel.tank', string='Tank', required=True, ondelete='cascade')
    dip_mm = fields.Float(string='Dip (mm)', required=True, digits=(16, 1))
    litres = fields.Float(string='Litres', required=True, digits=(16, 2))

    _dip_unique = models.Constraint(
        'UNIQUE(tank_id, dip_mm)',
        'That dip reading is already on this tank\'s chart.',
    )
    _dip_positive = models.Constraint(
        'CHECK(dip_mm >= 0)',
        'A dip cannot be negative.',
    )
    _litres_positive = models.Constraint(
        'CHECK(litres >= 0)',
        'Litres cannot be negative.',
    )
