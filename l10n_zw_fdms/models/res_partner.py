import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    l10n_zw_tin = fields.Char(
        string="ZIMRA TIN", size=10,
        help="10-digit Taxpayer Identification Number. Required on B2B fiscal "
             "invoices (ZIMRA Public Notice 30 of 2025).",
    )
    l10n_zw_vat_number = fields.Char(
        string="ZIMRA VAT Number", size=9,
        help="9-digit VAT registration number, if VAT-registered.",
    )

    @api.constrains('l10n_zw_tin', 'l10n_zw_vat_number')
    def _check_l10n_zw_numbers(self):
        for partner in self:
            if partner.l10n_zw_tin and not re.fullmatch(r'\d{10}', partner.l10n_zw_tin):
                raise ValidationError(_("The ZIMRA TIN must be exactly 10 digits."))
            if partner.l10n_zw_vat_number and not re.fullmatch(r'\d{9}', partner.l10n_zw_vat_number):
                raise ValidationError(_("The ZIMRA VAT number must be exactly 9 digits."))

    def _l10n_zw_buyer_data(self):
        """buyerData block for FDMS receipts, or None when nothing to report."""
        self.ensure_one()
        if not (self.l10n_zw_tin or self.l10n_zw_vat_number or self.is_company):
            return None
        buyer = {'buyerRegisterName': (self.name or '')[:200]}
        if self.l10n_zw_tin:
            buyer['buyerTIN'] = self.l10n_zw_tin
        if self.l10n_zw_vat_number:
            buyer['VATNumber'] = self.l10n_zw_vat_number
        contacts = {}
        if self.phone:
            contacts['phoneNo'] = self.phone[:20]
        if self.email:
            contacts['email'] = self.email[:100]
        if contacts:
            buyer['buyerContacts'] = contacts
        address = {}
        if self.state_id:
            address['province'] = self.state_id.name
        if self.city:
            address['city'] = self.city
        if self.street:
            address['street'] = self.street
        if self.street2:
            address['houseNo'] = self.street2
        if address:
            buyer['buyerAddress'] = address
        return buyer
