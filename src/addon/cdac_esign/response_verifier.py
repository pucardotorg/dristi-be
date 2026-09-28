"""Verification of the ESP response before it is trusted (spec 0015 #8.1).

The callback endpoint is public and unauthenticated, so the XMLDSig signature
over the response — checked against the configured C-DAC certificate, with SHA-1
excluded — is what stops anyone who learns a ``txn`` from injecting a signature.
"""

from datetime import datetime

from django.utils import timezone
from lxml import etree
from signxml import (
    DigestAlgorithm,
    InvalidInput,
    InvalidSignature,
    SignatureConfiguration,
    SignatureMethod,
    XMLVerifier,
)

ACCEPTED_SIGNATURE_METHODS = frozenset(
    {
        SignatureMethod.RSA_SHA256,
        SignatureMethod.RSA_SHA384,
        SignatureMethod.RSA_SHA512,
    }
)
ACCEPTED_DIGEST_ALGORITHMS = frozenset(
    {
        DigestAlgorithm.SHA256,
        DigestAlgorithm.SHA384,
        DigestAlgorithm.SHA512,
    }
)


class CDACResponseUntrusted(Exception):  # noqa: N818
    """Raised when the response signature is absent, invalid or from another key."""


class CDACResponseStale(Exception):  # noqa: N818
    """Raised when the response timestamp is outside the accepted window."""


def verify_response_signature(document: str, certificate_pem: str) -> None:
    """Verify the enveloped XMLDSig of ``document`` against ``certificate_pem``."""

    if not certificate_pem:
        raise CDACResponseUntrusted("No C-DAC response certificate is configured.")

    try:
        root = etree.fromstring(
            document.encode() if isinstance(document, str) else document,
            parser=etree.XMLParser(resolve_entities=False, no_network=True),
        )
    except etree.XMLSyntaxError as exc:
        raise CDACResponseUntrusted("The response document is not well-formed XML.") from exc

    try:
        XMLVerifier().verify(
            root,
            x509_cert=normalise_pem(certificate_pem),
            expect_config=SignatureConfiguration(
                require_x509=True,
                expect_references=1,
                signature_methods=ACCEPTED_SIGNATURE_METHODS,
                digest_algorithms=ACCEPTED_DIGEST_ALGORITHMS,
            ),
        )
    except (InvalidSignature, InvalidInput) as exc:
        raise CDACResponseUntrusted("The response signature did not verify.") from exc
    except Exception as exc:
        # signxml raises a wide range of parsing and cryptography errors; none
        # of them mean "trusted", and none of their messages are safe to leak.
        raise CDACResponseUntrusted("The response signature could not be verified.") from exc


def check_timestamp_freshness(
    moment: datetime | None,
    *,
    max_skew_seconds: int,
    now: datetime | None = None,
) -> None:
    """Reject a response whose ``ts`` is missing or outside the skew window."""

    if moment is None:
        raise CDACResponseStale("The response carries no usable timestamp.")
    now = now or timezone.now()
    if abs((now - moment).total_seconds()) > max_skew_seconds:
        raise CDACResponseStale("The response timestamp is outside the accepted window.")


def normalise_pem(certificate: str) -> str:
    """Accept a PEM block, a PEM with escaped newlines, or bare base64."""

    text = certificate.strip().replace("\\n", "\n")
    if "BEGIN CERTIFICATE" in text:
        return text
    body = "\n".join(text[index : index + 64] for index in range(0, len(text), 64))
    return f"-----BEGIN CERTIFICATE-----\n{body}\n-----END CERTIFICATE-----\n"
