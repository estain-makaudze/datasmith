# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


CONSIGNMENT_STATES = [
    ('draft', 'Draft'),
    ('quoted', 'Quoted'),
    ('in_clearance', 'In Clearance'),
    ('released', 'Released'),
    ('in_transit', 'In Transit'),
    ('delivered', 'Delivered'),
    ('invoiced', 'Invoiced'),
    ('closed', 'Closed'),
    ('cancelled', 'Cancelled'),
]


class FreightConsignment(models.Model):
    """The digital job file — one per shipment the clearing agent handles.

    Replaces the physical manila folder that today carries the CRN on the
    cover, the shipping documents inside, the handwritten duty worksheet,
    and the running cost sheet. Everything downstream in the module
    (disbursements, quotes, deposits, invoicing, demurrage) hangs off a
    consignment.
    """
    _name = 'freight.consignment'
    _description = 'Freight Consignment (Job File)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_opened desc, id desc'
    _rec_names_search = ['name', 'client_ref', 'client_id']

    # Identity ---------------------------------------------------------
    name = fields.Char(string='CRN', default='New', copy=False,
                       readonly=True, required=True, tracking=True,
                       help='Consignment Reference Number — written on the '
                            'cover of the job file.')
    client_id = fields.Many2one(
        'res.partner', string='Client', required=True, tracking=True,
        domain="[('is_freight_client', '=', True)]")
    client_ref = fields.Char(string='Client Reference', tracking=True,
                             help='The reference the importer uses: PO number, '
                                  'order number, their internal file.')
    user_id = fields.Many2one(
        'res.users', string='Clerk',
        default=lambda self: self.env.user, tracking=True)
    date_opened = fields.Date(
        string='Opened', default=fields.Date.context_today, required=True,
        tracking=True)
    eta = fields.Date(string='ETA', tracking=True,
                      help='Expected final delivery date communicated to the client.')
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company)

    # Shipment ---------------------------------------------------------
    mode = fields.Selection([
        ('road', 'Road'),
        ('sea', 'Sea'),
        ('air', 'Air'),
    ], string='Mode', required=True, default='road', tracking=True)
    direction = fields.Selection([
        ('import', 'Import'),
        ('export', 'Export'),
        ('transit', 'Transit'),
    ], string='Direction', required=True, default='import', tracking=True)
    origin = fields.Char(string='Origin', tracking=True,
                         help='Where the goods ship from.')
    destination = fields.Char(string='Destination', tracking=True,
                              help='Where the goods are finally delivered.')
    port_entry_id = fields.Many2one(
        'freight.port', string='Port of Entry', tracking=True,
        help='Border, sea port or airport where the consignment enters.')
    port_exit_id = fields.Many2one(
        'freight.port', string='Port of Exit', tracking=True,
        help='For exports or transit; otherwise leave blank.')
    incoterm = fields.Selection([
        ('exw', 'EXW — Ex Works'),
        ('fob', 'FOB — Free on Board'),
        ('cif', 'CIF — Cost, Insurance, Freight'),
        ('cfr', 'CFR — Cost and Freight'),
        ('dap', 'DAP — Delivered at Place'),
        ('ddp', 'DDP — Delivered Duty Paid'),
    ], string='Incoterm', tracking=True)
    truck_registration = fields.Char(string='Truck Reg', tracking=True)
    driver_name = fields.Char(string='Driver', tracking=True)
    container_no = fields.Char(string='Container No.', tracking=True)
    seal_no = fields.Char(string='Seal No.')

    # Invoice and currency --------------------------------------------
    invoice_value = fields.Monetary(
        string='Commercial Invoice Value', tracking=True,
        currency_field='invoice_currency_id',
        help='Value declared on the supplier commercial invoice.')
    invoice_currency_id = fields.Many2one(
        'res.currency', string='Invoice Currency',
        default=lambda self: self._default_currency(), required=True,
        tracking=True)

    # HS lines & duty totals ------------------------------------------
    hs_line_ids = fields.One2many(
        'freight.hs.line', 'consignment_id', string='HS Lines',
        copy=True)
    estimated_duty = fields.Monetary(
        string='Estimated Duty', compute='_compute_duty_totals',
        store=True, currency_field='invoice_currency_id',
        help='Sum of customs duty, VAT and surtax across HS lines.')
    estimated_customs_duty = fields.Monetary(
        string='Customs Duty', compute='_compute_duty_totals', store=True,
        currency_field='invoice_currency_id')
    estimated_vat = fields.Monetary(
        string='VAT', compute='_compute_duty_totals', store=True,
        currency_field='invoice_currency_id')
    estimated_surtax = fields.Monetary(
        string='Surtax', compute='_compute_duty_totals', store=True,
        currency_field='invoice_currency_id')

    # Documents --------------------------------------------------------
    document_ids = fields.One2many(
        'freight.consignment.document', 'consignment_id',
        string='Documents', copy=False)
    document_count = fields.Integer(compute='_compute_counts')
    hs_line_count = fields.Integer(compute='_compute_counts')

    # State ------------------------------------------------------------
    state = fields.Selection(
        CONSIGNMENT_STATES, string='Status', default='draft',
        required=True, tracking=True, copy=False, index=True)
    boe_entry_no = fields.Char(string='ASYCUDA Entry No.', copy=False,
                               tracking=True,
                               help='Entered manually when the clerk gets the '
                                    'Bill of Entry number back from ASYCUDA.')
    boe_entry_date = fields.Date(string='Entry Date', copy=False, tracking=True)
    release_date = fields.Date(string='Release Date', copy=False, tracking=True)
    delivered_date = fields.Date(string='Delivery Date', copy=False,
                                 tracking=True)
    closed_date = fields.Date(string='Closed Date', copy=False, readonly=True)

    notes = fields.Text(string='Internal Notes')

    # ---------------------------------------------------------------- defaults

    @api.model
    def _default_currency(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'freight_module.default_currency_id')
        if param:
            try:
                cur = self.env['res.currency'].browse(int(param)).exists()
                if cur:
                    return cur.id
            except (TypeError, ValueError):
                pass
        return self.env.company.currency_id.id

    # ---------------------------------------------------------------- create

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'freight.consignment') or 'New'
        return super().create(vals_list)

    # ---------------------------------------------------------------- display

    @api.depends('name', 'client_id')
    def _compute_display_name(self):
        for c in self:
            parts = [c.name] if c.name and c.name != 'New' else []
            if c.client_id:
                parts.append(c.client_id.name)
            c.display_name = ' — '.join(parts) if parts else _('New Consignment')

    # ---------------------------------------------------------------- computes

    @api.depends('hs_line_ids.duty_amount',
                 'hs_line_ids.vat_amount',
                 'hs_line_ids.surtax_amount')
    def _compute_duty_totals(self):
        for c in self:
            c.estimated_customs_duty = sum(
                line.duty_amount for line in c.hs_line_ids)
            c.estimated_vat = sum(line.vat_amount for line in c.hs_line_ids)
            c.estimated_surtax = sum(
                line.surtax_amount for line in c.hs_line_ids)
            c.estimated_duty = (c.estimated_customs_duty
                                + c.estimated_vat
                                + c.estimated_surtax)

    def _compute_counts(self):
        for c in self:
            c.document_count = len(c.document_ids)
            c.hs_line_count = len(c.hs_line_ids)

    # ---------------------------------------------------------------- actions

    def action_set_in_clearance(self):
        """Draft → In Clearance. Clerk has opened the job file and is now
        working the Bill of Entry on ASYCUDA."""
        for c in self:
            if c.state not in ('draft', 'quoted'):
                raise UserError(_(
                    "Only draft or quoted consignments can be moved to "
                    "In Clearance."))
            if not c.client_id:
                raise UserError(_("Set a client before moving to clearance."))
            c.state = 'in_clearance'

    def action_mark_released(self):
        """In Clearance → Released. ASYCUDA Release Order has come through."""
        for c in self:
            if c.state != 'in_clearance':
                raise UserError(_(
                    "Only consignments in clearance can be released."))
            c.state = 'released'
            if not c.release_date:
                c.release_date = fields.Date.context_today(c)

    def action_mark_in_transit(self):
        """Released → In Transit. Truck has collected and is on its way."""
        for c in self:
            if c.state != 'released':
                raise UserError(_(
                    "Only released consignments can go in transit."))
            c.state = 'in_transit'

    def action_mark_delivered(self):
        """In Transit → Delivered. Driver has returned a signed POD."""
        for c in self:
            if c.state != 'in_transit':
                raise UserError(_(
                    "Only in-transit consignments can be marked delivered."))
            c.state = 'delivered'
            if not c.delivered_date:
                c.delivered_date = fields.Date.context_today(c)

    def action_close(self):
        """Delivered or Invoiced → Closed. Job file archived."""
        for c in self:
            if c.state not in ('delivered', 'invoiced'):
                raise UserError(_(
                    "Only delivered or invoiced consignments can be closed."))
            c.state = 'closed'
            c.closed_date = fields.Date.context_today(c)

    def action_cancel(self):
        for c in self:
            if c.state == 'closed':
                raise UserError(_("Closed consignments cannot be cancelled."))
            c.state = 'cancelled'

    def action_reset_to_draft(self):
        for c in self:
            if c.state not in ('cancelled', 'quoted'):
                raise UserError(_(
                    "Only cancelled or quoted consignments can be reset to draft."))
            c.state = 'draft'

    # ---------------------------------------------------------------- views

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Documents'),
            'res_model': 'freight.consignment.document',
            'view_mode': 'list,form',
            'domain': [('consignment_id', '=', self.id)],
            'context': {'default_consignment_id': self.id},
        }

    def action_view_hs_lines(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('HS Lines'),
            'res_model': 'freight.hs.line',
            'view_mode': 'list,form',
            'domain': [('consignment_id', '=', self.id)],
            'context': {'default_consignment_id': self.id},
        }
