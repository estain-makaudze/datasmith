# Part of the ZIMRA fiscalisation suite.
{
    'name': 'Zimbabwe - Accounting',
    'icon': '/account/static/description/l10n.png',
    'countries': ['zw'],
    'version': '1.0',
    'category': 'Accounting/Localizations/Account Charts',
    'description': """
Base chart of accounts and taxes for Zimbabwe.

Provides a minimal chart of accounts, the current ZIMRA VAT rates
(15.5% standard, 0% zero-rated, exempt, 5% non-VAT withholding) and the
ZIMRA FDMS tax identifiers used by the fiscalisation module (l10n_zw_fdms).
    """,
    'depends': [
        'account',
    ],
    'auto_install': ['account'],
    'data': [
        'views/account_tax_views.xml',
    ],
    'license': 'LGPL-3',
}
