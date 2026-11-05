from odoo import fields, models


class SageSyncLog(models.Model):
    """One row per HTTP round-trip against the Sage Web API. The daily screen
    for finance: did it work, when, how long, and what did Sage actually say.

    Kept as its own model (not a Text field on the job) so logs are queryable,
    filterable, and survive the job being deleted.
    """

    _name = "sage.sync.log"
    _description = "Sage 300 HTTP Log"
    _order = "started_at desc, id desc"
    _rec_name = "endpoint"

    job_id = fields.Many2one("sage.sync.job", ondelete="cascade", index=True)
    config_id = fields.Many2one("sage.config", ondelete="cascade", index=True)

    method = fields.Char(required=True, help="HTTP verb: GET/POST/PATCH/DELETE.")
    endpoint = fields.Char(required=True, help="The URL path hit, e.g. /AR/InvoiceBatches.")
    status_code = fields.Integer(index=True)
    duration_ms = fields.Integer(help="Round-trip time, milliseconds.")

    started_at = fields.Datetime(default=fields.Datetime.now, required=True)
    finished_at = fields.Datetime()

    request_body = fields.Text()
    response_body = fields.Text()
    error = fields.Text(help="Populated when the call raised (timeout, DNS, parse, etc.).")

    success = fields.Boolean(compute="_compute_success", store=True)

    def _compute_success(self):
        for rec in self:
            rec.success = bool(rec.status_code) and 200 <= rec.status_code < 300 and not rec.error
