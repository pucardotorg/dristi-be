"""Builders for ``<EsignResp>`` documents used by the addon tests."""

import base64

from lxml import etree
from signxml import SignatureConstructionMethod, XMLSigner

from addon.cdac_esign.request_builder import format_timestamp
from addon.cdac_esign.xml_signer import C14N_ALGORITHM, DIGEST_ALGORITHM, SIGNATURE_METHOD

from .keys import esp_key_pair, signer_key_pair

# A minimal DER PKCS#7 SignedData ContentInfo: SEQUENCE { OID signedData }.
PKCS7_BLOB = bytes((0x30, 0x0B, 0x06, 0x09, 0x2A, 0x86, 0x48, 0x86, 0xF7, 0x0D, 0x01, 0x07, 0x02))
PKCS7_BASE64 = base64.b64encode(PKCS7_BLOB).decode()


def signer_certificate_base64() -> str:
    """Base64 DER of the stand-in signer certificate."""

    from cryptography.hazmat.primitives import serialization

    der = signer_key_pair().certificate.public_bytes(serialization.Encoding.DER)
    return base64.b64encode(der).decode()


def build_response(
    *,
    txn: str = "orders-1",
    status: str = "1",
    timestamp=None,
    result_code: str = "OK",
    error_code: str = "",
    error_message: str = "",
    signatures=None,
    certificate: str | None = None,
) -> str:
    """Return an ``<EsignResp>`` document as a string.

    ``signatures`` is a list of ``(value, error)`` tuples; ``None`` means one
    valid PKCS#7 signature.
    """

    from django.utils import timezone

    root = etree.Element(
        "EsignResp",
        {
            "status": status,
            "ts": format_timestamp(timestamp or timezone.now()),
            "txn": txn,
            "resCode": result_code,
            "errCode": error_code,
            "errMsg": error_message,
        },
    )
    certificate_element = etree.SubElement(root, "UserX509Certificate")
    certificate_element.text = (
        certificate if certificate is not None else signer_certificate_base64()
    )

    container = etree.SubElement(root, "Signatures")
    entries = signatures if signatures is not None else [(PKCS7_BASE64, "")]
    for index, (value, error) in enumerate(entries, start=1):
        element = etree.SubElement(container, "DocSignature", {"id": str(index), "error": error})
        element.text = value

    return etree.tostring(root, encoding="unicode")


def sign_document(document: str, key_pair=None) -> str:
    """Return ``document`` with an enveloped XMLDSig signature."""

    key_pair = key_pair or esp_key_pair()
    signer = XMLSigner(
        method=SignatureConstructionMethod.enveloped,
        signature_algorithm=SIGNATURE_METHOD,
        digest_algorithm=DIGEST_ALGORITHM,
        c14n_algorithm=C14N_ALGORITHM,
    )
    signed = signer.sign(
        etree.fromstring(document.encode()),
        key=key_pair.private_key,
        cert=[key_pair.certificate_pem],
    )
    return etree.tostring(signed, encoding="unicode")


def signed_response(**kwargs) -> str:
    """Return a signed ``<EsignResp>`` document."""

    return sign_document(build_response(**kwargs))
