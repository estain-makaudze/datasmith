import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SageSyncJob(models.Model):
    """Queue row — one record per pending (or failed) push to Sage.

    Design: trading never blocks on Sage. Posting an invoice in Odoo enqueues
    a sync.job; the actual HTTP call to Sage happens asynchronously from an
    ir.cron. If Sage is down the queue backs up; when it comes back the cron
    drains it. Finance sees the queue in the dashboard view.
    """

    _name = "sage.sync.job"
    _description = "Sage 300 Sync Job"
    _order = "scheduled_at asc, id asc"
    _rec_name = "display_name"

    config_id = fields.Many2one("sage.config", required=True, ondelete="cascade")
    move_id = fields.Many2one("account.move", required=True, ondelete="cascade")

    display_name = fields.Char(compute="_compute_display_name", store=True)

    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("dead", "Dead-Letter"),
        ],
        default="pending",
        index=True,
        required=True,
    )
    attempt = fields.Integer(default=0, readonly=True)
    scheduled_at = fields.Datetime(default=fields.Datetime.now, index=True)
    started_at = fields.Datetime(readonly=True)
    finished_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    log_ids = fields.One2many("sage.sync.log", "job_id")

    @api.depends("move_id", "status")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.status}] {rec.move_id.name or '?'}"

    # ---------------------------------------------------------------------
    # Enqueue entry point — called from account.move post hook
    # ---------------------------------------------------------------------
    @api.model
    def enqueue(self, move, config=None):
        """Create a pending job for `move`. Idempotent: if an undone job for the
        same (config, move) already exists, return it instead of creating a dup."""
        config = config or self.env["sage.config"]._get_default_config()
        if not config:
            raise UserError(_("No Sage configuration found. Create one in Sage 300 → Configuration."))
        existing = self.search(
            [
                ("config_id", "=", config.id),
                ("move_id", "=", move.id),
                ("status", "in", ("pending", "running", "failed")),
            ],
            limit=1,
        )
        if existing:
            return existing
        return self.create({"config_id": config.id, "move_id": move.id})

    # ---------------------------------------------------------------------
    # Worker — picked up by ir.cron
    # ---------------------------------------------------------------------
    @api.model
    def _cron_drain(self, batch_size=20):
        """Pick up to `batch_size` due jobs and process them."""
        due = self.search(
            [
                ("status", "in", ("pending", "failed")),
                ("scheduled_at", "<=", fields.Datetime.now()),
            ],
            limit=batch_size,
            order="scheduled_at asc",
        )
        _logger.info("sage_bridge: draining %s due sync jobs", len(due))
        for job in due:
            try:
                job._run()
            except Exception as e:   # noqa: BLE001 — queue worker catches all
                _logger.exception("sage_bridge: job %s crashed", job.id)
                job._mark_failed(str(e))

    def _run(self):
        """Execute one job: push the invoice to Sage, update mappings, mark done."""
        self.ensure_one()
        from ..services.sage_api import SageApi, SageApiError

        self.write({
            "status": "running",
            "started_at": fields.Datetime.now(),
            "attempt": self.attempt + 1,
        })

        client = SageApi(self.config_id, job=self)
        try:
            result = client.push_invoice(self.move_id)
            # Save mapping
            mapping = self.env["sage.invoice.mapping"].search(
                [("config_id", "=", self.config_id.id), ("move_id", "=", self.move_id.id)],
                limit=1,
            )
            vals = {
                "config_id": self.config_id.id,
                "move_id": self.move_id.id,
                "sage_batch_number": result.get("batch_number"),
                "sage_document_number": result.get("document_number"),
                "sage_posted": result.get("posted", False),
                "synced_at": fields.Datetime.now(),
            }
            if mapping:
                mapping.write(vals)
            else:
                self.env["sage.invoice.mapping"].create(vals)
            self.write({"status": "done", "finished_at": fields.Datetime.now()})
        except SageApiError as e:
            self._mark_failed(str(e))

    def _mark_failed(self, message):
        """Fail the job and either schedule a retry or move to dead-letter."""
        self.ensure_one()
        now = fields.Datetime.now()
        if self.attempt >= self.config_id.max_retries:
            self.write({
                "status": "dead",
                "finished_at": now,
                "last_error": message,
            })
            _logger.error("sage_bridge: job %s moved to dead-letter after %s attempts: %s",
                          self.id, self.attempt, message)
            return

        # Exponential backoff: base * 5^(attempt-1)  (1m, 5m, 25m for base=60)
        delay = self.config_id.retry_backoff_seconds * (5 ** (self.attempt - 1))
        next_at = now + timedelta(seconds=delay)
        self.write({
            "status": "failed",
            "finished_at": now,
            "last_error": message,
            "scheduled_at": next_at,
        })
        _logger.warning("sage_bridge: job %s failed (attempt %s), retry at %s: %s",
                        self.id, self.attempt, next_at, message)

    # ---------------------------------------------------------------------
    # UI actions
    # ---------------------------------------------------------------------
    def action_retry_now(self):
        """Force-retry a failed/dead job immediately."""
        for rec in self:
            rec.write({"status": "pending", "scheduled_at": fields.Datetime.now()})
        return True

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("HTTP Logs"),
            "res_model": "sage.sync.log",
            "view_mode": "list,form",
            "domain": [("job_id", "=", self.id)],
            "context": {"search_default_job_id": self.id},
        }
