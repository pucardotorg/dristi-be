"""Enveloped XMLDSig signing of the eSign request (spec 0015 #7.2).

Exclusive canonicalisation, SHA-256 digest, RSA-SHA256 signature, enveloped
transform, and the ASP ``X509Certificate`` in ``KeyInfo`` — the combination the
C-DAC ESP validates the request with.
"""

from lxml import etree
from signxml import (
    CanonicalizationMethod,
    DigestAlgorithm,
    SignatureConstructionMethod,
    SignatureMethod,
    XMLSigner,
)

from .keystore import ASPKeyMaterial

SIGNATURE_METHOD = SignatureMethod.RSA_SHA256
DIGEST_ALGORITHM = DigestAlgorithm.SHA256
C14N_ALGORITHM = CanonicalizationMethod.EXCLUSIVE_XML_CANONICALIZATION_1_0


class CDACXMLSigningError(Exception):
    """Raised when the request XML cannot be signed."""


def sign_request_xml(xml: bytes, key_material: ASPKeyMaterial) -> bytes:
    """Return ``xml`` with an enveloped XMLDSig signature appended."""

    try:
        document = etree.fromstring(xml)
    except etree.XMLSyntaxError as exc:
        raise CDACXMLSigningError("The request XML could not be parsed.") from exc

    signer = XMLSigner(
        method=SignatureConstructionMethod.enveloped,
        signature_algorithm=SIGNATURE_METHOD,
        digest_algorithm=DIGEST_ALGORITHM,
        c14n_algorithm=C14N_ALGORITHM,
    )
    try:
        signed = signer.sign(
            document,
            key=key_material.private_key,
            cert=[key_material.certificate_pem()],
        )
    except Exception as exc:
        raise CDACXMLSigningError("The request XML could not be signed.") from exc

    return etree.tostring(signed, xml_declaration=False, encoding="UTF-8")
