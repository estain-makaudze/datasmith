# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class FuelAttendant(models.Model):
    _name = 'fuel.attendant'
    _description = 'Forecourt Attendant'
    _order = 'site_id, name'

    name = fields.Char(string='Name', required=True)
    active = fields.Boolean(default=True)
    site_id = fields.Many2one('fuel.site', string='Site', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='site_id.company_id', store=True)
    code = fields.Char(string='Staff Number')
    phone = fields.Char(string='Phone')
    national_id = fields.Char(string='National ID')
    user_id = fields.Many2one(
        'res.users', string='Login',
        help='Optional. Set this when the attendant captures their own shift on a phone.')
    partner_id = fields.Many2one(
        'res.partner', string='Accounting Partner', copy=False, readonly=True,
        help='Carries any till shortage owed by this attendant. Created automatically.')
    is_supervisor = fields.Boolean(
        string='Can Supervise',
        help='Supervisors dip tanks, close shifts and receive tankers.')

    _code_site_uniq = models.Constraint(
        'UNIQUE(code, site_id)',
        'Another attendant at this site already has that staff number.',
    )

    @api.depends('name', 'site_id')
    def _compute_display_name(self):
        for attendant in self:
            site = attendant.site_id.code
            attendant.display_name = (
                '%s (%s)' % (attendant.name, site) if site else attendant.name)

    def _prepare_partner_vals(self):
        self.ensure_one()
        return {
            'name': self.name,
            'company_id': self.company_id.id,
            'phone': self.phone,
            'comment': _('Forecourt attendant at %s.') % self.site_id.display_name,
        }

    @api.model_create_multi
    def create(self, vals_list):
        attendants = super().create(vals_list)
        for attendant in attendants:
            if not attendant.partner_id:
                attendant.partner_id = self.env['res.partner'].create(
                    attendant._prepare_partner_vals())
        return attendants

    def write(self, vals):
        res = super().write(vals)
        if 'name' in vals or 'phone' in vals:
            for attendant in self.filtered('partner_id'):
                attendant.partner_id.write({
                    'name': attendant.name, 'phone': attendant.phone})
        return res
