"""Response verification tests (spec 0015 #8.1)."""

from datetime import timedelta

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
