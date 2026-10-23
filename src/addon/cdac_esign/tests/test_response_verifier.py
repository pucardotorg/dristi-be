"""Response verification tests (spec 0015 #8.1)."""

import base64
import hashlib
import xml.etree.ElementTree as StdET
from datetime import timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from django.test import SimpleTestCase
from django.utils import timezone

from addon.cdac_esign.response_verifier import (
    CDACResponseStale,
    CDACResponseUntrusted,
    check_timestamp_freshness,
    normalise_pem,
    verify_response_signature,
)

from .keys import asp_key_pair, esp_key_pair
from .responses import build_response, sign_document


class SignatureVerificationTests(SimpleTestCase):
    """XMLDSig verification against the configured C-DAC certificate."""

    def test_valid_signature_verifies(self):
        """A response signed by the configured key is trusted."""
        document = sign_document(build_response())
        self.assertIsNone(verify_response_signature(document, esp_key_pair().certificate_pem))

    def test_tampered_document_is_rejected(self):
        """Changing a single attribute invalidates the digest."""
        document = sign_document(build_response(txn="orders-1")).replace(
            'txn="orders-1"', 'txn="orders-2"'
        )
        with self.assertRaises(CDACResponseUntrusted):
            verify_response_signature(document, esp_key_pair().certificate_pem)

    def test_signature_from_another_key_is_rejected(self):
        """Anyone who learns a txn still cannot inject a signature."""
        document = sign_document(build_response(), key_pair=asp_key_pair())
        with self.assertRaises(CDACResponseUntrusted):
            verify_response_signature(document, esp_key_pair().certificate_pem)

    def test_unsigned_response_is_rejected(self):
        """An unsigned response carries no authenticity at all."""
        with self.assertRaises(CDACResponseUntrusted):
            verify_response_signature(build_response(), esp_key_pair().certificate_pem)

    def test_missing_certificate_is_rejected(self):
        """Without a configured certificate nothing can be trusted."""
        document = sign_document(build_response())
        with self.assertRaises(CDACResponseUntrusted):
            verify_response_signature(document, "")

    def test_malformed_document_is_rejected(self):
        """An unparsable document is never trusted."""
        with self.assertRaises(CDACResponseUntrusted):
            verify_response_signature("<EsignResp", esp_key_pair().certificate_pem)

    def test_bare_base64_certificate_is_accepted(self):
        """A certificate injected without PEM armour still works."""
        pem = esp_key_pair().certificate_pem
        bare = "".join(line for line in pem.splitlines() if "CERTIFICATE" not in line)
        document = sign_document(build_response())

        self.assertIn("BEGIN CERTIFICATE", normalise_pem(bare))
        self.assertIsNone(verify_response_signature(document, bare))


class TimestampFreshnessTests(SimpleTestCase):
    """``ts`` freshness."""

    def test_recent_timestamp_is_accepted(self):
        """A response inside the skew window is fresh."""
        self.assertIsNone(check_timestamp_freshness(timezone.now(), max_skew_seconds=900))

    def test_old_timestamp_is_rejected(self):
        """A replayed response from yesterday is refused."""
        with self.assertRaises(CDACResponseStale):
            check_timestamp_freshness(timezone.now() - timedelta(hours=2), max_skew_seconds=900)

    def test_future_timestamp_is_rejected(self):
        """Clock skew is bounded in both directions."""
        with self.assertRaises(CDACResponseStale):
            check_timestamp_freshness(timezone.now() + timedelta(hours=2), max_skew_seconds=900)

    def test_missing_timestamp_is_rejected(self):
        """A response with no usable ts cannot be shown to be fresh."""
        with self.assertRaises(CDACResponseStale):
            check_timestamp_freshness(None, max_skew_seconds=900)


DSIG_NS = "http://www.w3.org/2000/09/xmldsig#"


def cdac_style_response(key_pair=None, *, status="1", txn="orders-1") -> str:
    """Return a response shaped exactly like the C-DAC staging ESP's.

    A default-namespaced <Signature> (no ds: prefix), CRLF line breaks and
    RSA-SHA1 over a SHA-1 digest, as captured from a real C-DAC callback.
    signxml refuses to create SHA-1 signatures, so this one is built by hand;
    the canonical forms come from the standard library, independently of the
    lxml behaviour the verifier works around.
    """

    key_pair = key_pair or esp_key_pair()
    body = (
        f'<EsignResp errCode="NA" errMsg="NA" resCode="r-1" status="{status}" '
        f'ts="2026-10-23T15:05:14.708" txn="{txn}">'
        "<UserX509Certificate>QUJD</UserX509Certificate>"
        '<Signatures><DocSignature error="NA" id="1" sigHashAlgorithm="SHA256">'
        "MAsGCSqGSIb3DQEHAg==</DocSignature></Signatures>"
    )
    digest = base64.b64encode(
        hashlib.sha1(StdET.canonicalize(body + "</EsignResp>").encode()).digest()
    ).decode()
    signed_info = (
        "<SignedInfo>\r\n"
        '<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315">'
        "</CanonicalizationMethod>\r\n"
        f'<SignatureMethod Algorithm="{DSIG_NS}rsa-sha1"></SignatureMethod>\r\n'
        '<Reference URI="">\r\n<Transforms>\r\n'
        f'<Transform Algorithm="{DSIG_NS}enveloped-signature"></Transform>\r\n'
        "</Transforms>\r\n"
        f'<DigestMethod Algorithm="{DSIG_NS}sha1"></DigestMethod>\r\n'
        f"<DigestValue>{digest}</DigestValue>\r\n</Reference>\r\n</SignedInfo>"
    )
    # C14N of SignedInfo as it sits in the document: the default namespace is
    # inherited from <Signature>, and CRs in character content become &#xD;.
    canonical = StdET.canonicalize(
        signed_info.replace("<SignedInfo>", f'<SignedInfo xmlns="{DSIG_NS}">', 1)
    )
    value = base64.b64encode(
        key_pair.private_key.sign(canonical.encode(), padding.PKCS1v15(), hashes.SHA1())
    ).decode()
    return (
        f'{body}<Signature xmlns="{DSIG_NS}">\r\n{signed_info}\r\n'
        f"<SignatureValue>{value}</SignatureValue>\r\n</Signature></EsignResp>"
    )


class CDACStyleResponseTests(SimpleTestCase):
    """The response shape the real C-DAC ESP sends (RSA-SHA1, default namespace)."""

    def certificate(self):
        return esp_key_pair().certificate_pem

    def test_cdac_response_verifies_when_sha1_is_allowed(self):
        """Regression: a genuine C-DAC response was reported as untrusted."""
        self.assertIsNone(
            verify_response_signature(cdac_style_response(), self.certificate(), allow_sha1=True)
        )

    def test_sha1_is_refused_unless_allowed(self):
        """SHA-1 stays opt-in through CDAC_ESIGN_ALLOW_SHA1_RESPONSE."""
        with self.assertRaises(CDACResponseUntrusted):
            verify_response_signature(cdac_style_response(), self.certificate())

    def test_tampered_cdac_response_is_rejected(self):
        """Allowing SHA-1 and the xmlns fix do not weaken the digest check."""
        document = cdac_style_response()
        for original, forged in (
            ('status="1"', 'status="0"'),
            ('txn="orders-1"', 'txn="orders-2"'),
            ("MAsGCSqGSIb3DQEHAg==", "MAsGCSqGSIb3DQEHAh=="),
        ):
            with self.subTest(forged=forged), self.assertRaises(CDACResponseUntrusted):
                verify_response_signature(
                    document.replace(original, forged, 1), self.certificate(), allow_sha1=True
                )

    def test_cdac_response_signed_by_another_key_is_rejected(self):
        document = cdac_style_response(key_pair=asp_key_pair())
        with self.assertRaises(CDACResponseUntrusted):
            verify_response_signature(document, self.certificate(), allow_sha1=True)
