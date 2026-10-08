"""Provider-level tests for the C-DAC integration (spec 0015 #3, #7, #8)."""

import base64
import uuid
from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from lxml import etree

from addon.cdac_esign import constants
from addon.cdac_esign.provider import CDACESignProvider
from apps.esign.constants import (
    ESIGN_PROVIDER_REJECTED,
    ESIGN_SIGNATURE_INVALID,
    ESIGN_SIGNATURE_MISSING,
    ESignStatus,
)
from apps.esign.exceptions import (
    ESignCallbackMalformed,
    ESignRequestSigningFailed,
    ESignResponseStale,
    ESignResponseUntrusted,
)
from apps.esign.models import ESignTransaction
from apps.esign.providers import get_provider, reset_provider_cache
from apps.esign.services import process_callback

from .base import CDACSettingsMixin
from .keys import asp_key_pair
from .responses import PKCS7_BASE64, build_response, sign_document, signed_response


class BuildInitiationTests(CDACSettingsMixin, TestCase):
    """``build_initiation``."""

    def setUp(self):
        """Configure the addon and build an unsaved transaction."""
        self.configure()
        self.provider = CDACESignProvider()
        self.transaction = ESignTransaction(
            id=uuid.uuid4(),
            module="orders",
            entity_type="ORDER",
            entity_id="9f2c",
            provider=constants.PROVIDER_NAME,
            source_file_id="source-1",
            expires_at=timezone.now() + timedelta(seconds=900),
        )

    def decode(self, initiation):
        """Return the signed request XML carried by the form."""

        return etree.fromstring(
            base64.b64decode(initiation.form_fields[constants.FORM_FIELD_REQUEST])
        )

    def test_form_fields_carry_the_signed_request(self):
        """The UI posts these fields verbatim to the ESP."""
        initiation = self.provider.build_initiation(self.transaction, "a1b2c3")

        self.assertEqual(initiation.esign_url, "https://esign.cdac.invalid/esign")
        self.assertEqual(initiation.provider_transaction_id, f"orders-{self.transaction.pk}")
        self.assertEqual(
            initiation.form_fields[constants.FORM_FIELD_ASP_TXN],
            initiation.provider_transaction_id,
        )
        self.assertEqual(
            initiation.form_fields[constants.FORM_FIELD_CONTENT_TYPE], "application/xml"
        )

        root = self.decode(initiation)
        self.assertEqual(root.tag, constants.ESIGN_ELEMENT)
        self.assertEqual(root.get("txn"), initiation.provider_transaction_id)
        self.assertEqual(root.findall("./Docs/InputHash")[0].text, "a1b2c3")
        self.assertIsNotNone(root.find("{http://www.w3.org/2000/09/xmldsig#}Signature"))

    def test_request_audit_holds_no_key_material(self):
        """Only non-sensitive request metadata is handed to the domain."""
        audit = self.provider.build_initiation(self.transaction, "a1b2c3").request_audit
        rendered = str(audit)

        self.assertEqual(audit["asp_id"], "ASP-TEST")
        self.assertEqual(audit["hash_algorithm"], "SHA256")
        self.assertNotIn("PRIVATE KEY", rendered)
        self.assertNotIn("keystore-secret", rendered)

    def test_unusable_keystore_is_a_signing_failure(self):
        """A keystore problem is reported without naming the path."""
        self.configure(CDAC_ESIGN_KEYSTORE_PASSWORD="wrong-password")

        with self.assertRaises(ESignRequestSigningFailed) as caught:
            self.provider.build_initiation(self.transaction, "a1b2c3")
        self.assertNotIn("/", caught.exception.message)


class ParseAndVerifyTests(CDACSettingsMixin, TestCase):
    """``parse_response`` and ``verify_response``."""

    def setUp(self):
        """Configure the addon."""
        self.configure()
        self.provider = CDACESignProvider()

    def test_successful_response_is_parsed(self):
        """The signature and the certificate metadata reach the domain."""
        parsed = self.provider.parse_response({"msg": signed_response(txn="orders-1")})

        self.assertTrue(parsed.success)
        self.assertEqual(parsed.provider_transaction_id, "orders-1")
        self.assertEqual(parsed.signature, PKCS7_BASE64)
        self.assertIn("Signer Test", parsed.response_audit["signer_certificate_subject"])
        self.assertEqual(parsed.response_audit["signature_count"], 1)

    def test_provider_error_codes_are_mapped_to_internal_codes(self):
        """The domain never sees a C-DAC code."""
        parsed = self.provider.parse_response(
            {"msg": build_response(status="0", error_code="ESP-77", error_message="denied")}
        )

        self.assertEqual(parsed.error_code, ESIGN_PROVIDER_REJECTED)
        self.assertEqual(parsed.response_audit["provider_error_code"], "ESP-77")

    def test_missing_signature_is_reported_precisely(self):
        """A success with no signature gets its own failure code."""
        parsed = self.provider.parse_response({"msg": build_response(signatures=[("", "")])})
        self.assertEqual(parsed.error_code, ESIGN_SIGNATURE_MISSING)

    def test_unusable_signature_is_reported_precisely(self):
        """A blob that is not PKCS#7 gets its own failure code."""
        parsed = self.provider.parse_response(
            {"msg": build_response(signatures=[(base64.b64encode(b"x").decode(), "")])}
        )
        self.assertEqual(parsed.error_code, ESIGN_SIGNATURE_INVALID)

    def test_malformed_payload_is_rejected(self):
        """A payload with nothing to parse is a rejection."""
        with self.assertRaises(ESignCallbackMalformed):
            self.provider.parse_response({"unrelated": "value"})

    def test_valid_response_verifies(self):
        """A response signed by the configured C-DAC key is trusted."""
        self.assertIsNone(self.provider.verify_response({"msg": signed_response()}))

    def test_unsigned_response_is_untrusted(self):
        """Verification is what makes the public callback safe."""
        with self.assertRaises(ESignResponseUntrusted):
            self.provider.verify_response({"msg": build_response()})

    def test_tampered_response_is_untrusted(self):
        """A modified txn invalidates the signature."""
        document = sign_document(build_response(txn="orders-1")).replace(
            'txn="orders-1"', 'txn="orders-2"'
        )
        with self.assertRaises(ESignResponseUntrusted):
            self.provider.verify_response({"msg": document})

    def test_stale_response_is_rejected(self):
        """A replayed response outside the skew window is refused."""
        document = signed_response(timestamp=timezone.now() - timedelta(hours=2))
        with self.assertRaises(ESignResponseStale):
            self.provider.verify_response({"msg": document})

    def test_verification_can_be_disabled_locally(self):
        """Only local and CI may skip verification; production checks refuse it."""
        self.configure(CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE=False, CDAC_ESIGN_RESPONSE_CERT="")
        self.assertIsNone(self.provider.verify_response({"msg": build_response()}))


class CallbackThroughTheDomainTests(CDACSettingsMixin, TestCase):
    """The domain driving the real C-DAC provider."""

    def setUp(self):
        """Select the addon as the active provider and stub the modules."""
        self.configure()
        reset_provider_cache()
        self.addCleanup(reset_provider_cache)

        from apps.esign.tests.base import SOURCE_PDF
        from apps.esign.tests.fakes import FakeFileClient, FakePDFClient

        self.files = FakeFileClient()
        self.pdf = FakePDFClient()
        from unittest.mock import patch

        for target in (
            "apps.esign.services.callback.get_file_client",
            "apps.esign.services.callback.get_pdf_client",
        ):
            patcher = patch(target, return_value=self.files if "file" in target else self.pdf)
            patcher.start()
            self.addCleanup(patcher.stop)

        prepared = self.pdf.prepare_for_signing(SOURCE_PDF, {"page": 1})
        self.transaction = ESignTransaction.objects.create(
            module="orders",
            entity_type="ORDER",
            entity_id="9f2c",
            provider=constants.PROVIDER_NAME,
            provider_transaction_id="orders-cdac-1",
            source_file_id=self.files.add(SOURCE_PDF),
            placeholder_file_id=self.files.add(prepared.prepared_document),
            document_hash=prepared.document_hash,
            signature_field_name=prepared.field_name,
            status=ESignStatus.PENDING.value,
            expires_at=timezone.now() + timedelta(seconds=900),
        )

    def test_the_addon_is_the_selected_provider(self):
        """Selection is purely a settings change."""
        self.assertIsInstance(get_provider(), CDACESignProvider)

    def test_signed_response_completes_the_transaction(self):
        """A genuine C-DAC response drives the flow to SUCCESS."""
        payload = {"msg": signed_response(txn="orders-cdac-1")}

        outcome = process_callback(payload)

        self.transaction.refresh_from_db()
        self.assertEqual(outcome.status, ESignStatus.SUCCESS.value)
        self.assertTrue(self.transaction.signed_file_id)
        self.assertEqual(len(self.pdf.embed_calls), 1)
        self.assertNotIn("signature", self.transaction.response_audit)

    def test_response_signed_by_another_key_cannot_complete_it(self):
        """Anyone who learns a txn still cannot inject a signature."""
        payload = {"msg": sign_document(build_response(txn="orders-cdac-1"), asp_key_pair())}

        with self.assertRaises(ESignResponseUntrusted):
            process_callback(payload)

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.PENDING.value)
        self.assertEqual(self.pdf.embed_calls, [])

    @override_settings(CDAC_ESIGN_RESPONSE_FIELD="esignResp")
    def test_configured_response_field_is_honoured(self):
        """The ASP onboarding pack decides the form field name."""
        self.reset_caches()
        outcome = process_callback({"esignResp": signed_response(txn="orders-cdac-1")})
        self.assertEqual(outcome.status, ESignStatus.SUCCESS.value)
