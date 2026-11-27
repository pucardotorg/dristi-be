"""The DSC provider's initiation and completion contract (spec 0038 #3, #7)."""

import uuid
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from addon.dsc_esign.provider import DSCESignProvider
from apps.esign.exceptions import ESignCallbackMalformed, ESignResponseUntrusted
from apps.esign.providers.base import Completion

DIGEST = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"


def _txn():
    return SimpleNamespace(
        pk=uuid.UUID("7c9e2b10-0000-4000-8000-000000000001"),
        signature_field_name="Signature1",
        sign_placeholder={"page": 1, "x": 380, "y": 60, "width": 150, "height": 45},
    )


@override_settings(
    DSC_ESIGN_AGENT_URL="http://localhost:1620/sign", PDF_SIGNATURE_HASH_ALGORITHM="SHA256"
)
class DSCProviderTests(SimpleTestCase):
    """DSC completes from a client signature, never from the ESP callback."""

    def setUp(self):
        self.provider = DSCESignProvider()

    def test_completion_is_client_signature(self):
        self.assertEqual(self.provider.completion, Completion.CLIENT_SIGNATURE)
        self.assertEqual(self.provider.name, "dsc")

    def test_build_initiation_returns_the_agent_url_and_digest(self):
        initiation = self.provider.build_initiation(_txn(), DIGEST)
        self.assertEqual(initiation.esign_url, "http://localhost:1620/sign")
        self.assertEqual(initiation.form_fields["digest"], DIGEST)
        self.assertEqual(initiation.form_fields["hash_algorithm"], "sha256")
        self.assertEqual(initiation.form_fields["field_name"], "Signature1")
        self.assertEqual(initiation.form_fields["cood"], "380,60")
        self.assertTrue(initiation.provider_transaction_id.startswith("dsc-"))

    def test_parse_response_raises(self):
        with self.assertRaises(ESignCallbackMalformed):
            self.provider.parse_response({"txn": "dsc-1"})

    def test_verify_response_raises(self):
        with self.assertRaises(ESignResponseUntrusted):
            self.provider.verify_response({"txn": "dsc-1"})
