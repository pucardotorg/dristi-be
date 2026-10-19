"""Parsing of the ``<EsignResp>`` document (spec 0015 #7.3).

Unknown extra elements are ignored, because the ESP may add fields; anything
structurally wrong is a rejection rather than a guess.
"""

import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime

from cryptography import x509
from lxml import etree

from . import constants

# ContentInfo ::= SEQUENCE { contentType OBJECT IDENTIFIER, ... } where the
# signedData OID is 1.2.840.113549.1.7.2. Checking the DER prologue confirms
# the blob is a PKCS#7 SignedData before it is handed to the PDF Service;
# ``cryptography`` exposes no general CMS parser to do it with.
DER_SEQUENCE_TAG = 0x30
DER_OID_TAG = 0x06
PKCS7_SIGNED_DATA_OID = bytes((0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x07, 0x02))

# Length of ``yyyy-MM-dd'T'HH:mm:ss``.
TIMESTAMP_LENGTH = 19


class CDACResponseMalformed(Exception):  # noqa: N818
    """Raised when the response document cannot be read."""


# Why a signature problem is not an exception: the response still correlates
# to a transaction, so the domain can record the failure on that row and offer
# a retry. Only a document that cannot be correlated at all is raised on.
SIGNATURE_OK = ""
SIGNATURE_MISSING = "MISSING"
SIGNATURE_INVALID = "INVALID"


@dataclass(frozen=True)
class ParsedCDACResponse:
    """The fields of an ``<EsignResp>`` document this module acts on."""

    transaction_id: str
    status: str
    result_code: str = ""
    error_code: str = ""
    error_message: str = ""
    signature: str | None = None
    signer_certificate: str | None = None
    timestamp: datetime | None = None
    signature_count: int = 0
    signature_error: str = SIGNATURE_OK
    certificate_audit: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Whether the ESP reported a usable, completed signature."""

        return (
            self.status == constants.RESPONSE_SUCCESS_STATUS
            and self.signature_error == SIGNATURE_OK
        )


def extract_response_document(payload, config) -> str:
    """Return the response XML carried by a callback payload.

    The configured field name wins; otherwise the known C-DAC field names are
    tried, and finally any single value that looks like an ``<EsignResp>``
    document — which is what an interceptor forwarding a raw body produces.
    """

    if isinstance(payload, str):
        return payload
    if not hasattr(payload, "get"):
        raise CDACResponseMalformed("The callback payload is not a form or document.")

    names = []
    if getattr(config, "response_field", ""):
        names.append(config.response_field)
    names.extend(constants.RESPONSE_FIELD_CANDIDATES)

    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value

    for value in payload.values():
        if isinstance(value, str) and constants.RESPONSE_ELEMENT in value:
            return value

    raise CDACResponseMalformed("The callback payload carries no eSign response document.")


def parse_response_xml(
    document: str,
    *,
    expected_signature_count: int = constants.EXPECTED_SIGNATURE_COUNT,
) -> ParsedCDACResponse:
    """Parse and validate an ``<EsignResp>`` document."""

    root = _parse(document)
    if etree.QName(root).localname != constants.RESPONSE_ELEMENT:
        raise CDACResponseMalformed("The response document is not an eSign response.")

    transaction_id = (root.get("txn") or "").strip()
    if not transaction_id:
        raise CDACResponseMalformed("The response document carries no transaction id.")

    status = (root.get("status") or "").strip()
    signatures = _doc_signatures(root)
    certificate = _text(root, constants.USER_CERTIFICATE_ELEMENT)

    parsed_status_success = status == constants.RESPONSE_SUCCESS_STATUS
    if parsed_status_success and len(signatures) != expected_signature_count:
        raise CDACResponseMalformed(
            f"The response carries {len(signatures)} signature(s); "
            f"{expected_signature_count} was requested."
        )

    signature = None
    signature_error = SIGNATURE_OK
    if parsed_status_success:
        signature, signature_error = _read_signature(signatures[0])

    return ParsedCDACResponse(
        transaction_id=transaction_id,
        status=status,
        result_code=(root.get("resCode") or "").strip(),
        error_code=(root.get("errCode") or "").strip(),
        error_message=(root.get("errMsg") or "").strip(),
        signature=signature,
        signer_certificate=certificate or None,
        timestamp=parse_timestamp(root.get("ts")),
        signature_count=len(signatures),
        signature_error=signature_error,
        certificate_audit=certificate_audit(certificate),
    )


def _read_signature(entry) -> tuple[str | None, str]:
    """Return ``(signature, error)`` for a ``DocSignature`` element."""

    element, error = entry
    value = (element.text or "").strip()
    if error or not value:
        return None, SIGNATURE_MISSING
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None, SIGNATURE_INVALID
    if not decoded or not is_pkcs7_signed_data(decoded):
        return None, SIGNATURE_INVALID
    return value, SIGNATURE_OK


def is_pkcs7_signed_data(der: bytes) -> bool:
    """Whether ``der`` is a PKCS#7 ``SignedData`` ContentInfo."""

    if len(der) < 4 or der[0] != DER_SEQUENCE_TAG:
        return False
    offset = _skip_length(der, 1)
    if offset is None or offset >= len(der) or der[offset] != DER_OID_TAG:
        return False
    oid_length = der[offset + 1] if offset + 1 < len(der) else 0
    oid = der[offset + 2 : offset + 2 + oid_length]
    return oid == PKCS7_SIGNED_DATA_OID


def parse_timestamp(value) -> datetime | None:
    """Return the ESP timestamp as an aware datetime in IST."""

    if not value:
        return None
    text = str(value).strip()
    for parser in (_parse_cdac_timestamp, _parse_iso_timestamp):
        parsed = parser(text)
        if parsed is not None:
            return parsed
    return None


def certificate_audit(certificate: str) -> dict:
    """Return the signer-certificate metadata worth persisting.

    Only the subject and serial are recorded; the certificate itself is not
    persisted (spec 0015 #7.3).
    """

    if not certificate:
        return {}
    try:
        parsed = x509.load_der_x509_certificate(base64.b64decode(certificate, validate=True))
    except Exception:
        return {"signer_certificate_parsed": False}
    return {
        "signer_certificate_parsed": True,
        "signer_certificate_subject": parsed.subject.rfc4514_string(),
        "signer_certificate_serial": format(parsed.serial_number, "x"),
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _parse(document: str):
    """Parse the response document without resolving entities or the network."""

    if not document or not document.strip():
        raise CDACResponseMalformed("The response document is empty.")
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    data = document.strip()
    try:
        return etree.fromstring(data.encode() if isinstance(data, str) else data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise CDACResponseMalformed("The response document is not well-formed XML.") from exc


def _doc_signatures(root):
    """Return ``(element, error)`` for each ``DocSignature`` in the response."""

    return [
        (element, (element.get("error") or "").strip())
        for element in root.iter()
        if etree.QName(element).localname == constants.DOC_SIGNATURE_ELEMENT
    ]


def _text(root, local_name: str) -> str:
    """Return the stripped text of the first element with ``local_name``."""

    for element in root.iter():
        if etree.QName(element).localname == local_name:
            return (element.text or "").strip()
    return ""


def _skip_length(der: bytes, offset: int):
    """Return the offset just past a DER length field, or ``None``."""

    if offset >= len(der):
        return None
    first = der[offset]
    if first < 0x80:
        return offset + 1
    count = first & 0x7F
    if count == 0 or offset + 1 + count > len(der):
        return None
    return offset + 1 + count


def _parse_cdac_timestamp(text: str):
    """Parse the ``yyyy-MM-dd'T'HH:mm:ss`` IST form C-DAC sends."""

    try:
        naive = datetime.strptime(text[:TIMESTAMP_LENGTH], constants.TIMESTAMP_FORMAT)
    except ValueError:
        return None
    return naive.replace(tzinfo=constants.IST)


def _parse_iso_timestamp(text: str):
    """Parse an ISO-8601 timestamp, assuming IST when no offset is given."""

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=constants.IST)
    return parsed
