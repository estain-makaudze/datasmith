# Part of the ZIMRA fiscalisation suite.
{
    'name': 'Zimbabwe - ZIMRA FDMS Fiscalisation',
    'version': '1.0',
    'category': 'Accounting/Localizations/EDI',
    'countries': ['zw'],
    'summary': 'Fiscalise customer invoices and credit notes with ZIMRA FDMS',
    'description': """
ZIMRA FDMS (Fiscal Device Management System) integration for Zimbabwe.

- Virtual fiscal device registration (CSR / certificate flow)
- Receipt signing with hash chaining and gap-free counters
- Fiscal day management (open/close, counters, day signature)
- Queued, non-blocking submission with automatic retries
- QR verification code on invoices and credit notes
- Demo mode for testing without ZIMRA credentials

Extensible: any document source can plug into the shared fiscal document
model (see l10n_zw.fdms.document._create_for_record).
    """,
    'depends': [
        'account',
        'certificate',
        'l10n_zw',
    ],
    'external_dependencies': {
        'python': ['cryptography', 'requests'],
    },
    'data': [
        'security/fdms_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'wizards/fdms_register_wizard_views.xml',
        'wizards/fdms_close_day_wizard_views.xml',
        'views/fdms_device_views.xml',
        'views/fdms_fiscal_day_views.xml',
        'views/fdms_document_views.xml',
        'views/account_move_views.xml',
        'views/res_partner_views.xml',
        'views/report_invoice.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
}
