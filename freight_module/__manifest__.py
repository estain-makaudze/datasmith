# -*- coding: utf-8 -*-
{
    'name': "Freight & Clearing Agents",
    'version': '19.0.1.0.0',
    'category': 'Freight',
    'summary': "Customs clearance, consignment job files, disbursement "
               "ledger, deposits, demurrage watch and fiscalised invoicing "
               "for Zimbabwean clearing agents.",
    'description': """
Freight & Clearing Agents
=========================

Replaces the manila consignment file with a digital job file. Closes the
disbursement leak with a receipt-first ledger of every payment made on
behalf of a client. Tracks demurrage countdowns per port, exposes a
public no-login status page for importers, and posts fiscalised service
invoices into Odoo Accounting via l10n_zw_fdms.

Step 1 ships the master data: ports, HS codes, disbursement categories,
clients (importers) and transporters (sub-contracted truckers), plus the
settings page where the posting journals and accounts are configured.
""",
    'author': "zimpreneur",
    'website': "https://zimpreneur.co.zw",
    'depends': ['base', 'mail', 'account'],
    'data': [
        'security/freight_security.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/disbursement_categories.xml',
        'data/ports.xml',
        'views/freight_port_views.xml',
        'views/freight_hs_code_views.xml',
        'views/freight_disbursement_category_views.xml',
        'views/freight_client_views.xml',
        'views/freight_transporter_views.xml',
        'views/freight_consignment_views.xml',
        'views/res_config_settings_views.xml',
        'views/freight_menu_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'OPL-1',
}
