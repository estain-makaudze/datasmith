# -*- coding: utf-8 -*-
{
    'name': "Fuel Stations",
    'version': '19.0.1.0.0',
    'category': 'Fuel Retail',
    'summary': "Forecourt shift reconciliation, wet stock, deliveries, "
               "fleet credit and multi-site control for fuel dealers",
    'description': """
Fuel Stations
=============
Replaces the dip sheet and pump reconciliation book of a Zimbabwean fuel
station. Every shift produces two numbers: the wet stock variance in litres
and the cash variance in money, each with a tank or an attendant against it.
Odoo Accounting is touched only at the posting points.
    """,
    'author': "ePort",
    'website': "http://www.eport.cloud",
    'depends': ['base', 'mail', 'account', 'product'],
    'data': [
        'security/fuel_security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/fuel_payment_methods.xml',
        'views/product_template_views.xml',
        'views/fuel_site_views.xml',
        'views/fuel_tank_views.xml',
        'views/fuel_pump_views.xml',
        'views/fuel_nozzle_views.xml',
        'views/fuel_attendant_views.xml',
        'views/fuel_price_views.xml',
        'views/fuel_shift_views.xml',
        'wizard/fuel_dip_test_views.xml',
        'views/res_config_settings_views.xml',
        'views/fuel_menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'OPL-1',
}
