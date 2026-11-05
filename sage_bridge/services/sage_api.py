"""Sage 300 Web API client.

Writes against Sage's OData v4 REST surface. Shape of calls:

    GET  <base>/v1.0/-/<company>/AR/Customers?$top=1
    POST <base>/v1.0/-/<company>/AR/InvoiceBatches
    POST <base>/v1.0/-/<company>/AR/InvoiceEntries
    POST <base>/v1.0/-/<company>/AR/InvoiceBatches(<id>)/Post

This client is deliberately thin: one class, no abstraction gymnastics. It takes
a sage.config record, knows how to authenticate, and exposes a small set of
business-level methods (push_invoice, test_connection). Every call is logged
into sage.sync.log via the optional `job` argument.

The same client talks to a real Sage server OR the mock-Sage server shipped
alongside this module — no code branches. mock_mode is just a label on the
config; the mock responds to the same endpoints with the same shapes.
"""
import json
import logging
import time

import requests
from requests.auth import HTTPBasicAuth

from odoo import fields

_logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30  # seconds


class SageApiError(Exception):
    """Raised for any non-success response from Sage (or network failure)."""


class SageApi:
    """Thin REST client against Sage 300 Web API."""

    def __init__(self, config, job=None):
        """
        :param config: sage.config recordset (ensure_one'd)
        :param job:    optional sage.sync.job — if given, every HTTP call is logged
                       against it in sage.sync.log for the dashboard.
        """
        self.config = config
        self.job = job
        self.env = config.env
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(config.username, config.password or "")
        self._session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

    # ---------------------------------------------------------------------
    # High-level business operations
    # ---------------------------------------------------------------------
    def test_connection(self):
        """Lightweight read to confirm URL + auth + company code + API enabled."""
        try:
            resp = self._get("/AR/Customers", params={"$top": 1})
        except SageApiError as e:
            return False, f"Connection failed: {e}"
        return True, f"Connected. Company: {self.config.company_code}. HTTP 200."

    def push_invoice(self, move):
        """Create an AR batch with one invoice entry for `move`.

        Returns a dict:
            {"batch_number": "...", "document_number": "...", "posted": bool}

        Flow (matches Sage's batch model):
            1. Ensure customer exists in Sage (lookup, else create). Mapping cached.
            2. Create a new AR invoice batch.
            3. POST the invoice entry under that batch.
            4. Post the batch (so it hits the GL), store the resulting document number.
        """
        customer_number = self._ensure_customer(move.partner_id)

        # 1. Open batch
        batch_resp = self._post(
            "/AR/InvoiceBatches",
            payload={
                "BatchDescription": f"Odoo push {move.name}",
                "BatchDate": str(move.invoice_date or fields.Date.today()),
                "BankCode": "USD",
            },
        )
        batch_number = str(batch_resp.get("BatchNumber"))

        # 2. Add entry
        entry_payload = {
            "BatchNumber": batch_number,
            "CustomerNumber": customer_number,
            "DocumentType": "IN" if move.move_type == "out_invoice" else "CR",
            "DocumentNumber": move.name,
            "DocumentDate": str(move.invoice_date or fields.Date.today()),
            "DueDate": str(move.invoice_date_due or move.invoice_date or fields.Date.today()),
            "DocumentTotal": round(move.amount_total, 2),
            "ExternalReference": f"ODOO-{move.id}",   # idempotency key
            "Details": [
                {
                    "LineNumber": idx + 1,
                    "Description": line.name or line.product_id.display_name or "line",
                    "Quantity": round(line.quantity, 4),
                    "UnitPrice": round(line.price_unit, 4),
                    "LineAmount": round(line.price_subtotal, 2),
                    "DistributionCode": "SALES",
                }
                for idx, line in enumerate(move.invoice_line_ids)
            ],
        }
        entry_resp = self._post("/AR/InvoiceEntries", payload=entry_payload)
        document_number = str(entry_resp.get("DocumentNumber") or move.name)

        # 3. Post the batch to the GL
        try:
            post_resp = self._post(f"/AR/InvoiceBatches({batch_number})/Post", payload={})
            posted = bool(post_resp.get("Posted", True))
        except SageApiError as e:
            # Batch created + entry added, but post failed. Record document number;
            # a human (or retry) can post the batch later.
            _logger.warning("sage_bridge: entry created but batch post failed: %s", e)
            posted = False

        return {"batch_number": batch_number, "document_number": document_number, "posted": posted}

    # ---------------------------------------------------------------------
    # Customer sync — idempotent via sage.customer.mapping
    # ---------------------------------------------------------------------
    def _ensure_customer(self, partner):
        """Return Sage CustomerNumber for `partner`, creating it in Sage if missing.
        Mapping is cached in sage.customer.mapping so this is O(1) after first push.
        """
        Mapping = self.env["sage.customer.mapping"]
        existing = Mapping.search(
            [("config_id", "=", self.config.id), ("partner_id", "=", partner.id)],
            limit=1,
        )
        if existing:
            return existing.sage_customer_number

        # Derive a Sage-friendly customer number from partner ref or id
        customer_number = (partner.ref or f"ODOO{partner.id:06d}").upper()[:12]
        payload = {
            "CustomerNumber": customer_number,
            "CustomerName": partner.name,
            "GroupCode": "USD",
            "AccountSetCode": "USA",
            "TermsCode": "NET30",
            "AddressLine1": partner.street or "",
            "AddressLine2": partner.street2 or "",
            "City": partner.city or "",
            "Country": (partner.country_id.code or "ZW"),
        }
        self._post("/AR/Customers", payload=payload)
        Mapping.create({
            "config_id": self.config.id,
            "partner_id": partner.id,
            "sage_customer_number": customer_number,
            "last_pushed_payload": json.dumps(payload, indent=2),
        })
        return customer_number

    # ---------------------------------------------------------------------
    # HTTP primitives + logging
    # ---------------------------------------------------------------------
    def _url(self, path):
        base = self.config.base_url.rstrip("/")
        return f"{base}/v1.0/-/{self.config.company_code}{path}"

    def _get(self, path, params=None):
        return self._request("GET", path, params=params)

    def _post(self, path, payload):
        return self._request("POST", path, payload=payload)

    def _request(self, method, path, payload=None, params=None):
        url = self._url(path)
        log_vals = {
            "job_id": self.job.id if self.job else False,
            "config_id": self.config.id,
            "method": method,
            "endpoint": path,
            "request_body": json.dumps(payload, indent=2) if payload is not None else None,
            "started_at": fields.Datetime.now(),
        }
        started = time.monotonic()
        try:
            resp = self._session.request(
                method, url, json=payload, params=params, timeout=DEFAULT_TIMEOUT,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            log_vals.update({
                "status_code": resp.status_code,
                "duration_ms": duration_ms,
                "response_body": (resp.text or "")[:16000],
                "finished_at": fields.Datetime.now(),
            })
            self.env["sage.sync.log"].sudo().create(log_vals)

            if not resp.ok:
                raise SageApiError(f"HTTP {resp.status_code}: {(resp.text or '')[:400]}")
            try:
                return resp.json() if resp.content else {}
            except ValueError as e:
                raise SageApiError(f"Non-JSON response from Sage: {e} // {(resp.text or '')[:200]}")
        except requests.RequestException as e:
            duration_ms = int((time.monotonic() - started) * 1000)
            log_vals.update({
                "duration_ms": duration_ms,
                "error": str(e),
                "finished_at": fields.Datetime.now(),
            })
            self.env["sage.sync.log"].sudo().create(log_vals)
            raise SageApiError(f"Network error: {e}")
