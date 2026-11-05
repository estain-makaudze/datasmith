# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    is_fuel_grade = fields.Boolean(
        string='Fuel Grade',
        help='Tick for petrol, diesel, paraffin and other liquid fuels sold through '
             'a pump. Only these can be assigned to a tank.')
