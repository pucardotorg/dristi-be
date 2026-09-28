"""Provider contract, registry and mock-provider tests (spec 0015 #3)."""

import base64
import uuid
from datetime import timedelta

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from apps.esign.exceptions import ESignCallbackMalformed, ESignProviderNotConfigured
from apps.esign.models import ESignTransaction
from apps.esign.providers import get_provider, reset_provider_cache
from apps.esign.providers.base import ESignProvider
from apps.esign.providers.mock import MockESignProvider


class NotAProvider:
    """Deliberately not an :class:`ESignProvider`."""


class NamelessProvider(ESignProvider):
    """A provider that forgot to declare a name."""

    name = ""

    def build_initiation(self, transaction, document_hash):
        """Unused."""

    def parse_response(self, payload):
        """Unused."""

    def verify_response(self, payload):
        """Unused."""


class RegistryTests(SimpleTestCase):
    """``ESIGN_PROVIDER`` resolution."""

    def setUp(self):
        """Start from a cold cache so each setting is really resolved."""
        reset_provider_cache()
        self.addCleanup(reset_provider_cache)

    def test_default_is_the_mock_provider(self):
        """Local and CI need no ESP credentials."""
        self.assertIsInstance(get_provider(), MockESignProvider)

    def test_provider_is_cached(self):
        """The dotted path is resolved once."""
        self.assertIs(get_provider(), get_provider())

    @override_settings(ESIGN_PROVIDER="")
    def test_unset_provider_is_rejected(self):
        """An unset provider is a configuration error, not a silent no-op."""
        with self.assertRaises(ESignProviderNotConfigured):
            get_provider()

    @override_settings(ESIGN_PROVIDER="apps.esign.providers.nope.Missing")
    def test_unimportable_provider_is_rejected(self):
        """An unimportable path is reported as a configuration error."""
        with self.assertRaises(ESignProviderNotConfigured):
            get_provider()

    @override_settings(ESIGN_PROVIDER="apps.esign.tests.test_providers.NotAProvider")
    def test_non_provider_class_is_rejected(self):
        """Only ESignProvider subclasses may be configured."""
        with self.assertRaises(ESignProviderNotConfigured):
            get_provider()

    @override_settings(ESIGN_PROVIDER="apps.esign.tests.test_providers.NamelessProvider")
    def test_provider_without_a_name_is_rejected(self):
        """The name is persisted on every transaction, so it is required."""
        with self.assertRaises(ESignProviderNotConfigured):
            get_provider()


class MockProviderTests(SimpleTestCase):
    """The provider used locally and in CI."""

    def setUp(self):
        """Build an unsaved transaction the provider can read."""
        self.provider = MockESignProvider()
        self.transaction = ESignTransaction(
            id=uuid.uuid4(),
            module="orders",
            provider="mock",
            source_file_id="source-1",
            expires_at=timezone.now() + timedelta(seconds=900),
        )

    def test_initiation_carries_the_transaction_id_and_hash(self):
        """The form fields are opaque to the UI but correlate to the row."""
        initiation = self.provider.build_initiation(self.transaction, "abc123")

        self.assertEqual(initiation.provider_transaction_id, f"orders-{self.transaction.pk}")
        self.assertEqual(initiation.form_fields["aspTxnID"], initiation.provider_transaction_id)
        decoded = base64.b64decode(initiation.form_fields["eSignRequest"]).decode()
        self.assertEqual(decoded, f"{initiation.provider_transaction_id}:abc123")

    def test_successful_response_is_parsed(self):
        """A status of 1 with a signature is a success."""
        parsed = self.provider.parse_response(
            {"txn": "orders-1", "status": "1", "signature": "Zm9v", "certificate": "Y2VydA=="}
        )
        self.assertTrue(parsed.success)
        self.assertEqual(parsed.signature, "Zm9v")
        self.assertEqual(parsed.signer_certificate, "Y2VydA==")
        self.assertEqual(parsed.error_code, "")

    def test_failed_response_is_parsed(self):
        """Any other status is a failure carrying the ESP's code."""
        parsed = self.provider.parse_response(
            {"txn": "orders-1", "status": "0", "errCode": "E1", "errMsg": "cancelled"}
        )
        self.assertFalse(parsed.success)
        self.assertEqual(parsed.error_code, "E1")
        self.assertEqual(parsed.error_message, "cancelled")

    def test_payload_without_a_transaction_id_is_malformed(self):
        """A callback that correlates to nothing cannot be processed."""
        with self.assertRaises(ESignCallbackMalformed):
            self.provider.parse_response({"status": "1", "signature": "Zm9v"})

    def test_verification_is_a_no_op(self):
        """The mock ESP signs nothing; production checks refuse to use it."""
        self.assertIsNone(self.provider.verify_response({"txn": "orders-1"}))
