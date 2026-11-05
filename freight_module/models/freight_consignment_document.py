# -*- coding: utf-8 -*-
from odoo import api, fields, models


DOCUMENT_TYPES = [
    ('commercial_invoice', 'Commercial Invoice'),
    ('packing_list', 'Packing List'),
    ('bol', 'Bill of Lading / Air Waybill'),
    ('insurance', 'Insurance Certificate'),
    ('origin', 'Certificate of Origin'),
    ('duty_worksheet', 'Duty Worksheet'),
    ('boe', 'Bill of Entry (SAD)'),
    ('duty_receipt', 'Duty Receipt'),
    ('release', 'Release Order'),
    ('waybill', 'Transporter Waybill'),
    ('pod', 'Proof of Delivery'),
    ('fiscal_invoice', 'Fiscalised Invoice'),
    ('other', 'Other'),
]


class FreightConsignmentDocument(models.Model):
    """A document attached to a consignment job file.

    Mirrors a sheet in the manila folder: shipping docs, duty receipts,
    the SAD printout, the signed POD. Captured by phone photo or
    uploaded PDF — timestamped and attributed to whoever uploaded it.
    """
    _name = 'freight.consignment.document'
    _description = 'Consignment Document'
    _order = 'uploaded_at desc, id desc'
    _rec_name = 'display_label'

    consignment_id = fields.Many2one(
        'freight.consignment', string='Consignment', required=True,
        ondelete='cascade', index=True)
    type = fields.Selection(
        DOCUMENT_TYPES, string='Type', required=True, default='other')
    name = fields.Char(string='Description',
                       help='Short label — supplier invoice number, receipt reference, etc.')
    reference = fields.Char(string='Reference')
    attachment = fields.Binary(string='File', attachment=True, required=True)
    attachment_filename = fields.Char(string='Filename')
    uploaded_by = fields.Many2one(
        'res.users', string='Uploaded by',
        default=lambda self: self.env.user, readonly=True)
    uploaded_at = fields.Datetime(
        string='Uploaded at', default=fields.Datetime.now, readonly=True)
    notes = fields.Text()

    display_label = fields.Char(compute='_compute_display_label', store=False)

    @api.depends('type', 'name', 'reference')
    def _compute_display_label(self):
        type_map = dict(DOCUMENT_TYPES)
        for doc in self:
            parts = [type_map.get(doc.type) or '']
            if doc.reference:
                parts.append(doc.reference)
            elif doc.name:
                parts.append(doc.name)
            doc.display_label = ' — '.join(filter(None, parts)) or 'Document'
