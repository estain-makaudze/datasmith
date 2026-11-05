# ZIMRA FDMS Fiscalisation for Odoo 19

Generic, reusable ZIMRA (Zimbabwe Revenue Authority) fiscalisation suite:

| Module | Purpose |
|---|---|
| `l10n_zw` | Zimbabwe chart of accounts + VAT taxes (15.5% → ZIMRA taxID 515, 0% → 2, exempt → 3, 5% WHT → 514) and the `l10n_zw_tax_id` mapping fields on `account.tax`. |
| `l10n_zw_fdms` | The fiscalisation engine (this module). |

## What it does

- **Signs every posted customer invoice / credit note** with the device key
  (SHA-256 + ECDSA-P256), maintaining ZIMRA's per-day hash chain and gap-free
  `receiptGlobalNo` / `receiptCounter` under a device row-lock (multi-worker safe).
- **Never blocks trading**: signing is local; submission to the FDMS API is queued
  and retried by cron (`ZIMRA FDMS: submit fiscal documents`) with exponential
  backoff, strict chain ordering, and ambiguous-timeout reconciliation via GetStatus.
- **QR + verification code** on the invoice PDF immediately at posting.
- **Fiscal days**: auto-opened on first receipt, auto-closed by cron before
  `taxPayerDayMaxHrs`, with counters recomputed from the immutable signed payloads
  and the day signature submitted via CloseDay (async, polled).
- **Credit notes** must reference a fiscalised original; the `creditDebitNote`
  block is late-bound at send time from the original's server `receiptID`.
- **B2B rules** (Public Notice 30/2025): companies need a 10-digit TIN
  (`res.partner.l10n_zw_tin`), optional 9-digit VAT number.
- **Immutability**: fiscalised invoices cannot be reset to draft; fiscal documents
  can never be deleted.

## Setup

1. Install `l10n_zw_fdms` (pulls in `l10n_zw`, `certificate`).
2. Make sure every sale tax carries a **ZIMRA Tax ID** (tax form → Advanced
   Options → ZIMRA). For an existing 15.5% tax set `515`.
3. Accounting → Configuration → ZIMRA Fiscalisation → **Fiscal Devices** → create:
   Device ID, serial and activation key from the ZIMRA taxpayer portal
   (Fiscalisation → register a *virtual device*), mode **Test** or **Production**.
   Mode **Demo** works fully offline with mocked ZIMRA responses.
4. Click **Register with ZIMRA**: verifies the taxpayer, generates the secp256r1
   key + CSR, obtains the device certificate, pulls the device config.
5. Post an invoice — it is signed instantly and queued for submission.

`ir.config_parameter` `l10n_zw_fdms.mock_base_url` points *Test* mode at a local
mock server (e.g. github.com/takumade/zimra-fdms-mock-server) for integration
testing.

## Extending to other document sources (POS, e-commerce…)

Everything flows through `l10n_zw.fdms.document._create_for_record(record_values)`.
A bridge module only needs to:

1. `_inherit = 'l10n_zw.fdms.document'` and add its FK (e.g. `pos_order_id`)
   plus extend `_get_record()`.
2. Build `record_values` (lines/taxes/payments dicts — see the docstring) at its
   finalisation hook and call `_create_for_record`.
3. Optionally override `_l10n_zw_get_money_type` mapping (Cash/Card/...).

Chain, day, device, signing, sending and retries are shared and untouched.

## ⚠ Before production

The exact encoding of `previousReceiptHash` in the signature string (base64
string, as both open-source reference implementations do, vs raw bytes) is
isolated in `fdms_signing._chain_hash_component()`. Validate a full fiscal day
against the ZIMRA **test** environment (clean close, no RCPT hash errors)
before switching the device to Production.

## Tests

    odoo-bin -d <db> -i l10n_zw,l10n_zw_fdms --test-enable --test-tags /l10n_zw_fdms --stop-after-init

Covers: byte-exact signature strings/QR (golden vectors), chain continuity,
day counters (sale vs credit note separation), credit-note guards, B2B TIN
enforcement, draft/delete locks, demo registration and full send/close cycle.
