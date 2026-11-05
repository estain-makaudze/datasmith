# -*- coding: utf-8 -*-
{
    'name': "Transport Management",
    'version': '19.0.1.0.0',
    'category': 'Transport',
    'summary': "Kombi and bus operations: fleet, routes, daily cash-ups, "
               "driver payment schemes, leave, and accounting integration",
    'description': """
Self-contained management of a passenger transport (kombi / bus) business:
vehicles, routes, drivers and conductors, daily cash-up sheets with operating
expenses, driver leave with allocations, and driver payments computed from
configurable schemes (fixed wage, commission on cash collected, or hybrid)
over weekly, fortnightly or monthly periods. Everything is custom to the
transport workflow; Odoo Accounting is integrated at the posting points —
cash-ups and payment runs create journal entries, and each driver carries a
partner so payables can be paid and reconciled per driver. USD/ZWG sheets
are supported through standard multi-currency.
""",
    'author': "ePort",
    'website': "http://www.eport.cloud",
    'depends': ['base', 'mail', 'account'],
    'data': [
        'security/transport_security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/leave_types.xml',
        'data/expense_types.xml',
        'views/transport_route_views.xml',
        'views/transport_expense_type_views.xml',
        'views/transport_payment_scheme_views.xml',
        'views/transport_vehicle_views.xml',
        'views/transport_vehicle_service_views.xml',
        'views/transport_driver_views.xml',
        'views/transport_leave_views.xml',
        'views/transport_cashup_views.xml',
        'views/transport_payment_run_views.xml',
        'wizard/payment_run_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/transport_menu_views.xml',
    ],
    'demo': [
        'demo/demo_currency.xml',
        'demo/demo_master.xml',
        'demo/demo_cashups.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'OPL-1',
}
