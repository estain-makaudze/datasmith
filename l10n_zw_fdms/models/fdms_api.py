import base64
import contextlib
import logging
import os
import tempfile
import uuid

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

BASE_URLS = {
    'test': 'https://fdmsapitest.zimra.co.zw',
    'prod': 'https://fdmsapi.zimra.co.zw',
}
QR_URLS = {
    'test': 'https://fdmstest.zimra.co.zw/',
    'prod': 'https://fdms.zimra.co.zw/',
}
TIMEOUT = 60


class L10nZwFdmsApi(models.AbstractModel):
    _name = 'l10n_zw.fdms.api'
    _description = 'ZIMRA FDMS API Client'

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    @api.model
    def _get_base_url(self, device):
        if device.mode == 'test':
            # Allows pointing the test mode at a local FDMS mock server.
            mock = self.env['ir.config_parameter'].sudo().get_param('l10n_zw_fdms.mock_base_url')
            if mock:
                return mock.rstrip('/')
        return BASE_URLS.get(device.mode, BASE_URLS['test'])

    @api.model
    @contextlib.contextmanager
    def _client_cert_files(self, device):
        """Yield (cert_path, key_path) tempfiles for requests' mTLS cert=."""
        cert = device.certificate_id
        key = device.key_id
        if not cert or not key:
            raise UserError(_("Device %s has no certificate/key; register it first.", device.name))
        cert_pem = base64.b64decode(cert.with_context(bin_size=False).pem_certificate)
        key_pem = base64.b64decode(key.with_context(bin_size=False).pem_key)
        cert_file = key_file = None
        try:
            cert_file = tempfile.NamedTemporaryFile(suffix='.pem', delete=False)
            key_file = tempfile.NamedTemporaryFile(suffix='.pem', delete=False)
            os.chmod(cert_file.name, 0o600)
            os.chmod(key_file.name, 0o600)
            cert_file.write(cert_pem)
            key_file.write(key_pem)
            cert_file.close()
            key_file.close()
            yield cert_file.name, key_file.name
        finally:
            for f in (cert_file, key_file):
                if f is not None:
                    with contextlib.suppress(OSError):
                        os.unlink(f.name)

    @api.model
    def _call_fdms(self, device, method, endpoint, payload=None, public=False):
        """Call an FDMS endpoint. Returns (error, data).

        error is None on success, else a dict with at least 'code' and
        'message'. Sentinel codes: 'CON' connection failure, 'TIM' timeout
        (outcome ambiguous — the request may have been processed), 'JSON'
        unparseable body, otherwise the HTTP status code as string.
        """
        if device.mode == 'demo':
            return None, self._get_demo_response(device, endpoint, payload)

        section = 'Public' if public else 'Device'
        url = f"{self._get_base_url(device)}/{section}/v1/{device.device_id}/{endpoint}"
        headers = {
            'DeviceModelName': device.model_name,
            'DeviceModelVersion': device.model_version,
            'Content-Type': 'application/json',
        }
        try:
            if public:
                response = requests.request(
                    method, url, json=payload, headers=headers, timeout=TIMEOUT)
            else:
                with self._client_cert_files(device) as cert:
                    response = requests.request(
                        method, url, json=payload, headers=headers,
                        cert=cert, timeout=TIMEOUT)
        except requests.exceptions.Timeout:
            _logger.warning("ZIMRA FDMS timeout on %s %s", method, url)
            return {'code': 'TIM', 'message': _("The FDMS request timed out.")}, None
        except requests.exceptions.RequestException as e:
            _logger.warning("ZIMRA FDMS connection error on %s %s: %s", method, url, e)
            return {'code': 'CON', 'message': _("Could not connect to the FDMS server: %s", e)}, None

        if not response.ok:
            detail = ''
            with contextlib.suppress(ValueError):
                body = response.json()
                detail = body.get('detail') or body.get('title') or str(body)
            _logger.warning("ZIMRA FDMS HTTP %s on %s %s: %s",
                            response.status_code, method, url, detail or response.text[:500])
            return {
                'code': str(response.status_code),
                'message': detail or _("FDMS returned HTTP %s.", response.status_code),
            }, None
        if not response.content:
            return None, {}
        try:
            return None, response.json()
        except ValueError:
            return {'code': 'JSON', 'message': _("FDMS returned an unreadable response.")}, None

    # ------------------------------------------------------------------
    # Demo mode
    # ------------------------------------------------------------------

    @api.model
    def _get_demo_response(self, device, endpoint, payload=None):
        """Local mock responses so the full lifecycle works without ZIMRA."""
        operation_id = f'DEMO-{uuid.uuid4().hex[:12].upper()}'
        now_iso = fields.Datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        if endpoint == 'VerifyTaxpayerInformation':
            return {
                'operationID': operation_id,
                'taxPayerName': device.company_id.name,
                'taxPayerTIN': '1000000000',
                'vatNumber': '100000000',
                'deviceBranchName': device.company_id.name,
            }
        if endpoint in ('RegisterDevice', 'IssueCertificate'):
            return {'operationID': operation_id, 'certificate': None}
        if endpoint == 'GetConfig':
            return {
                'operationID': operation_id,
                'taxPayerName': device.company_id.name,
                'taxPayerTIN': '1000000000',
                'vatNumber': '100000000',
                'deviceSerialNo': device.serial_number,
                'deviceBranchName': device.company_id.name,
                'deviceOperatingMode': 'Online',
                'taxPayerDayMaxHrs': 24,
                'taxpayerDayEndNotificationHrs': 20,
                'applicableTaxes': [
                    {'taxID': 1, 'taxName': 'Standard rated 15%', 'taxPercent': 15.0,
                     'validFrom': '2009-01-01'},
                    {'taxID': 2, 'taxName': 'Zero rated 0%', 'taxPercent': 0.0,
                     'validFrom': '2009-01-01'},
                    {'taxID': 3, 'taxName': 'Exempt', 'validFrom': '2009-01-01'},
                    {'taxID': 514, 'taxName': 'Non-VAT Withholding Tax', 'taxPercent': 5.0,
                     'validFrom': '2009-01-01'},
                    {'taxID': 515, 'taxName': 'Standard rated 15.5%', 'taxPercent': 15.5,
                     'validFrom': '2025-01-01'},
                ],
                'certificateValidTill': '2030-01-01T00:00:00',
                'qrUrl': QR_URLS['test'],
            }
        if endpoint == 'OpenDay':
            return {'operationID': operation_id,
                    'fiscalDayNo': (payload or {}).get('fiscalDayNo', 1)}
        if endpoint == 'SubmitReceipt':
            receipt = (payload or {}).get('receipt', {})
            return {
                'operationID': operation_id,
                'receiptID': 100000 + receipt.get('receiptGlobalNo', 0),
                'serverDate': now_iso,
                'receiptServerSignature': {
                    'hash': receipt.get('receiptDeviceSignature', {}).get('hash'),
                    'signature': 'DEMO',
                    'certificateThumbprint': 'DEMO',
                },
                'validationErrors': [],
            }
        if endpoint == 'CloseDay':
            return {'operationID': operation_id}
        if endpoint == 'GetStatus':
            day = device.current_fiscal_day_id
            status = 'FiscalDayOpened' if day and day.state == 'open' else 'FiscalDayClosed'
            if day and day.state == 'close_initiated':
                status = 'FiscalDayClosed'  # demo closes complete instantly
            return {
                'operationID': operation_id,
                'fiscalDayStatus': status,
                'lastReceiptGlobalNo': device.receipt_global_no,
                'lastFiscalDayNo': day.fiscal_day_no if day else 0,
            }
        if endpoint == 'Ping':
            return {'operationID': operation_id, 'reportingFrequency': 60}
        return {'operationID': operation_id}

    # ------------------------------------------------------------------
    # Registration / certificate lifecycle
    # ------------------------------------------------------------------

    @api.model
    def _generate_csr(self, device):
        """Generate (or reuse) the device key and build a PEM CSR."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.x509.oid import NameOID

        if not device.key_id:
            device.key_id = self.env['certificate.key']._generate_ec_private_key(
                device.company_id,
                name=f'zimra_device_{device.device_id}_key',
            )
        key_pem = base64.b64decode(device.key_id.with_context(bin_size=False).pem_key)
        private_key = serialization.load_pem_private_key(key_pem, None)
        subject = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME,
                               f'ZIMRA-{device.serial_number}-{device.device_id:010d}'),
            x509.NameAttribute(NameOID.COUNTRY_NAME, 'ZW'),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, 'Zimbabwe'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Zimbabwe Revenue Authority'),
        ])
        csr = (
            x509.CertificateSigningRequestBuilder()
            .subject_name(subject)
            .sign(private_key, hashes.SHA256())
        )
        return csr.public_bytes(serialization.Encoding.PEM).decode()

    @api.model
    def _store_certificate(self, device, certificate_pem):
        if not certificate_pem:
            if device.mode != 'demo':
                raise UserError(_("ZIMRA did not return a certificate."))
            # Demo mode: self-signed certificate so mTLS plumbing stays testable.
            certificate_pem = self._generate_self_signed_pem(device)
        cert = self.env['certificate.certificate'].create({
            'name': f'ZIMRA device {device.device_id} ({device.mode})',
            'content': base64.b64encode(certificate_pem.encode()),
            'private_key_id': device.key_id.id,
            'company_id': device.company_id.id,
            'scope': 'general',
        })
        device.certificate_id = cert
        if cert.date_end:
            device.certificate_valid_till = cert.date_end
        return cert

    @api.model
    def _generate_self_signed_pem(self, device):
        import datetime

        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.x509.oid import NameOID

        key_pem = base64.b64decode(device.key_id.with_context(bin_size=False).pem_key)
        private_key = serialization.load_pem_private_key(key_pem, None)
        name = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME,
                               f'ZIMRA-{device.serial_number}-{device.device_id:010d}'),
            x509.NameAttribute(NameOID.COUNTRY_NAME, 'ZW'),
        ])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=3650))
            .sign(private_key, hashes.SHA256())
        )
        return cert.public_bytes(serialization.Encoding.PEM).decode()

    @api.model
    def _register_device(self, device):
        """Full RegisterDevice flow: CSR -> certificate -> GetConfig."""
        csr_pem = self._generate_csr(device)
        error, data = self._call_fdms(
            device, 'POST', 'RegisterDevice',
            payload={
                'certificateRequest': csr_pem,
                'activationKey': device.activation_key,
            },
            public=True,
        )
        if error:
            raise UserError(_("Device registration failed: %s", error.get('message', error)))
        self._store_certificate(device, data.get('certificate'))
        device.state = 'registered'
        error, config = self._call_fdms(device, 'GET', 'GetConfig')
        if not error:
            device._apply_config(config)
        return True

    @api.model
    def _renew_certificate(self, device):
        csr_pem = self._generate_csr(device)
        error, data = self._call_fdms(
            device, 'POST', 'IssueCertificate',
            payload={'certificateRequest': csr_pem})
        if error:
            raise UserError(_("Certificate renewal failed: %s", error.get('message', error)))
        self._store_certificate(device, data.get('certificate'))
        return True
