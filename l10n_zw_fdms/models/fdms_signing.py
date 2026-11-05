"""Pure helpers building the ZIMRA FDMS signature strings, hashes and QR data.

Everything here is deliberately free of Odoo model dependencies so it can be
unit-tested byte-exact against the reference implementations (ZimraEGS C#,
zimra-public Python) and the ZIMRA test environment.

All monetary amounts are handled as Decimal and converted to integer cents
with ROUND_HALF_UP — float arithmetic must never touch a signature string.
"""

import base64
import hashlib
from decimal import Decimal, ROUND_HALF_UP

# Receipt types as accepted by the FDMS API.
RECEIPT_TYPE_FISCAL_INVOICE = 'FiscalInvoice'
RECEIPT_TYPE_CREDIT_NOTE = 'CreditNote'
RECEIPT_TYPE_DEBIT_NOTE = 'DebitNote'


def to_cents(amount):
    """Return the integer cents of a monetary amount, as a string.

    Accepts Decimal, str, int or float (floats are converted through str to
    shed binary representation noise). Negative amounts keep their sign,
    e.g. Decimal('-10.50') -> '-1050'.
    """
    dec = Decimal(str(amount))
    cents = (dec * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    return str(int(cents))


def format_percent(percent):
    """Format a tax percentage for signature strings: two decimals, or ''.

    ZIMRA requires exempt taxes to contribute an empty string (no percent),
    which is how exemption is distinguished from an actual 0% rate.
    """
    if percent is None or percent == '':
        return ''
    return f"{Decimal(str(percent)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def format_receipt_date(dt):
    """Local device time formatted as required by FDMS: yyyy-MM-ddTHH:mm:ss."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S')


def build_receipt_taxes_block(receipt_taxes):
    """Concatenate the receiptTaxes component of the signature string.

    :param receipt_taxes: list of dicts with keys taxID, taxPercent (str|None,
        already ''-for-exempt), taxAmount, salesAmountWithTax.
    """
    parts = []
    for tax in sorted(receipt_taxes, key=lambda t: (t['taxID'],)):
        parts.append(format_percent(tax.get('taxPercent')))
        parts.append(to_cents(tax['taxAmount']))
        parts.append(to_cents(tax['salesAmountWithTax']))
    return ''.join(parts)


def build_receipt_signature_string(device_id, receipt_type, currency, receipt_global_no,
                                   receipt_date, receipt_total, receipt_taxes,
                                   previous_receipt_hash_b64=None):
    """Build the exact string that is SHA-256 hashed and signed for a receipt.

    Confirmed against ZimraEGS ReceiptHelper and the zimra-public Python
    client:

        deviceID + receiptType.upper() + currency + receiptGlobalNo
        + receiptDate('yyyy-MM-ddTHH:mm:ss') + cents(receiptTotal)
        + <taxes block> [+ previousReceiptHash if receiptCounter > 1]

    :param previous_receipt_hash_b64: base64 string of the previous receipt's
        SHA-256 hash within the same fiscal day, or None for the first receipt
        of the day. Both reference implementations append the base64 string
        form; kept isolated here so a one-line change can fix the encoding if
        the official spec disagrees (see _chain_hash_component).
    """
    source = (
        str(device_id)
        + receipt_type.upper()
        + currency.upper()
        + str(receipt_global_no)
        + format_receipt_date(receipt_date)
        + to_cents(receipt_total)
        + build_receipt_taxes_block(receipt_taxes)
    )
    if previous_receipt_hash_b64:
        source += _chain_hash_component(previous_receipt_hash_b64)
    return source


def _chain_hash_component(previous_receipt_hash_b64):
    """The exact representation of the previous hash appended to the string.

    Reference implementations append the base64 string form. If verification
    against the ZIMRA test environment shows raw bytes/hex is expected, this
    is the single place to change.
    """
    return previous_receipt_hash_b64


def sha256_b64(source_string):
    """SHA-256 of the UTF-8 string, returned as (raw_digest, base64_str)."""
    digest = hashlib.sha256(source_string.encode('utf-8')).digest()
    return digest, base64.b64encode(digest).decode()


def build_fiscal_day_signature_string(device_id, fiscal_day_no, fiscal_day_date, counters):
    """Build the fiscal day (CloseDay) device signature source string.

    deviceID + fiscalDayNo + fiscalDayDate(yyyy-MM-dd) + counters block.

    Counters with a zero value are excluded. Counters are sorted by
    (type, currency, taxID, moneyType) and each contributes:

        fiscalCounterType.upper() + fiscalCounterCurrency.upper()
        + taxPercent '0.00' (tax counters, ''-for-exempt)
        + moneyType.upper() (BalanceByMoneyType counters)
        + cents(value)

    :param counters: list of dicts with keys fiscalCounterType,
        fiscalCounterCurrency, fiscalCounterTaxPercent (opt), fiscalCounterTaxID
        (opt), fiscalCounterMoneyType (opt), fiscalCounterValue.
    """
    def sort_key(c):
        return (
            c['fiscalCounterType'],
            c['fiscalCounterCurrency'],
            c.get('fiscalCounterTaxID') if c.get('fiscalCounterTaxID') is not None else -1,
            c.get('fiscalCounterMoneyType') or '',
        )

    parts = [str(device_id), str(fiscal_day_no), fiscal_day_date.strftime('%Y-%m-%d')]
    for counter in sorted(counters, key=sort_key):
        if to_cents(counter['fiscalCounterValue']) == '0':
            continue
        parts.append(counter['fiscalCounterType'].upper())
        parts.append(counter['fiscalCounterCurrency'].upper())
        if counter.get('fiscalCounterMoneyType'):
            parts.append(counter['fiscalCounterMoneyType'].upper())
        else:
            parts.append(format_percent(counter.get('fiscalCounterTaxPercent')))
        parts.append(to_cents(counter['fiscalCounterValue']))
    return ''.join(parts)


def compute_verification_code(device_signature_b64):
    """Derive the 16-character receipt verification code from the signature.

    Steps (per the zimra-public reference): base64-decode the device
    signature, hex-encode the bytes, MD5 the hex string, take the first 16
    hex characters uppercased.
    """
    signature_bytes = base64.b64decode(device_signature_b64)
    md5_hex = hashlib.md5(signature_bytes.hex().encode()).hexdigest()
    return md5_hex[:16].upper()


def build_qr_data(qr_url, device_id, receipt_date, receipt_global_no, device_signature_b64):
    """Build the full QR code payload / verification URL.

    {qrUrl}{deviceID:010d}{receiptDate:ddMMyyyy}{receiptGlobalNo:010d}{code16}
    """
    base = qr_url if qr_url.endswith('/') else qr_url + '/'
    return (
        f"{base}"
        f"{int(device_id):010d}"
        f"{receipt_date.strftime('%d%m%Y')}"
        f"{int(receipt_global_no):010d}"
        f"{compute_verification_code(device_signature_b64)}"
    )


def format_verification_code(code16):
    """Group the 16-char verification code as XXXX-XXXX-XXXX-XXXX."""
    return '-'.join(code16[i:i + 4] for i in range(0, 16, 4))
