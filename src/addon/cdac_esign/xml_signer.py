"""Enveloped XMLDSig signing of the eSign request (spec 0015 #7.2).

Inclusive C14N 1.0, SHA-256 digest, RSA-SHA256 signature and a single enveloped
transform, matching the C-DAC 2.1 reference ASP (``XmlSigning.signXmlStringNew``),
plus the ASP ``X509Certificate`` in ``KeyInfo``. The reference signs with
RSA-SHA1; SHA-1 is not used here.
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
C14N_ALGORITHM = CanonicalizationMethod.CANONICAL_XML_1_0


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
            # The reference request carries only the enveloped transform.
            exclude_c14n_transform_element=True,
        )
    except Exception as exc:
        raise CDACXMLSigningError("The request XML could not be signed.") from exc

    return etree.tostring(signed, xml_declaration=False, encoding="UTF-8")
