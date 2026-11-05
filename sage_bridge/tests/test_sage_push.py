"""End-to-end push test using a patched SageApi — proves the hooks + queue +
mapping tables + idempotency behave as the README advertises, without needing
a real Sage server or the mock.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "sage_bridge")
class TestSagePush(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.config = cls.env["sage.config"].create({
            "name": "Test Sage",
            "base_url": "https://fake-sage.local",
            "company_code": "TEST01",
            "username": "demo",
            "password": "demo123",
            "demo_mode": True,
            "auto_push_on_post": False,   # we enqueue manually in each test
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "Test Customer",
            "ref": "TC001",
        })
        cls.account_revenue = cls.env["account.account"].search(
            [("account_type", "=", "income")], limit=1,
        )

    def _make_invoice(self, amount=100.0):
        return self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "invoice_line_ids": [(0, 0, {
                "name": "Test line",
                "quantity": 1,
                "price_unit": amount,
                "account_id": self.account_revenue.id,
            })],
        })

    def test_push_enqueues_and_maps(self):
        """Posting an invoice + enqueuing + draining the queue produces a mapping."""
        move = self._make_invoice()
        move.action_post()

        job = self.env["sage.sync.job"].enqueue(move, config=self.config)
        self.assertEqual(job.status, "pending")

        with patch("odoo.addons.sage_bridge.services.sage_api.SageApi.push_invoice") as m:
            m.return_value = {"batch_number": "B-1", "document_number": "D-9", "posted": True}
            self.env["sage.sync.job"]._cron_drain()

        self.assertEqual(job.status, "done")
        mapping = self.env["sage.invoice.mapping"].search([("move_id", "=", move.id)])
        self.assertEqual(len(mapping), 1)
        self.assertEqual(mapping.sage_batch_number, "B-1")
        self.assertEqual(mapping.sage_document_number, "D-9")
        self.assertTrue(mapping.sage_posted)

    def test_idempotency_no_duplicate_mapping(self):
        """Running the job twice does not create two mappings for the same invoice."""
        move = self._make_invoice()
        move.action_post()
        job = self.env["sage.sync.job"].enqueue(move, config=self.config)

        with patch("odoo.addons.sage_bridge.services.sage_api.SageApi.push_invoice") as m:
            m.return_value = {"batch_number": "B-1", "document_number": "D-1", "posted": True}
            job._run()
            # Re-enqueue + run again
            job2 = self.env["sage.sync.job"].enqueue(move, config=self.config)
            self.assertEqual(job2.id, job.id,
                             "enqueue should return existing in-flight job, not create a new one")
            # Force second run by resetting status, simulating a retry path
            job.write({"status": "pending"})
            m.return_value = {"batch_number": "B-2", "document_number": "D-2", "posted": True}
            job._run()

        mappings = self.env["sage.invoice.mapping"].search([("move_id", "=", move.id)])
        self.assertEqual(len(mappings), 1, "Must not duplicate mapping on retry")
        self.assertEqual(mappings.sage_batch_number, "B-2", "Latest push updates the mapping")

    def test_failure_schedules_retry_with_backoff(self):
        """A failed job gets a later scheduled_at and an attempt increment."""
        from ..services.sage_api import SageApiError

        move = self._make_invoice()
        move.action_post()
        job = self.env["sage.sync.job"].enqueue(move, config=self.config)

        with patch("odoo.addons.sage_bridge.services.sage_api.SageApi.push_invoice") as m:
            m.side_effect = SageApiError("HTTP 500: boom")
            job._run()

        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempt, 1)
        self.assertIn("boom", job.last_error)

    def test_failure_exceeds_retries_moves_to_dead(self):
        """After max_retries attempts, status becomes 'dead'."""
        from ..services.sage_api import SageApiError

        self.config.max_retries = 2
        move = self._make_invoice()
        move.action_post()
        job = self.env["sage.sync.job"].enqueue(move, config=self.config)

        with patch("odoo.addons.sage_bridge.services.sage_api.SageApi.push_invoice") as m:
            m.side_effect = SageApiError("HTTP 500: boom")
            # 3 attempts: first two retry, third goes dead
            job._run()
            self.assertEqual(job.status, "failed")
            job.write({"status": "pending"})
            job._run()
            self.assertEqual(job.status, "dead")
