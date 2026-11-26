"""DSC client-signature completion end-to-end and capability separation (spec 0038 #14)."""

import base64
from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from addon.dsc_esign.tests.factories import detached_cms, make_signer
from apps.esign import errors
from apps.esign.constants import ESignStatus
from apps.esign.providers import reset_provider_cache

from .base import ESignTestCase

PROVIDERS = {
    "mock": "apps.esign.providers.mock.MockESignProvider",
    "dsc": "addon.dsc_esign.provider.DSCESignProvider",
}


@override_settings(
    ESIGN_PROVIDERS=PROVIDERS,
    ESIGN_DEFAULT_PROVIDER="mock",
    DSC_ESIGN_AGENT_URL="http://localhost:1620/sign",
    DSC_ESIGN_ALLOW_UNTRUSTED_CERT=True,
    PDF_SIGNATURE_HASH_ALGORITHM="SHA256",
)
class DSCCompletionTests(ESignTestCase):
    """The authenticated _complete endpoint verifies, embeds and stores."""

    def setUp(self):
        super().setUp()
        reset_provider_cache()
        self.addCleanup(reset_provider_cache)

    def _signed_pkcs7(self, transaction):
        signer = make_signer()
        digest = bytes.fromhex(transaction.document_hash)
        return base64.b64encode(detached_cms(signer, digest).dump()).decode()

    def test_initiation_returns_client_signature_and_the_agent_url(self):
        response = self.initiate(signing_method="dsc")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["completion"], "CLIENT_SIGNATURE")
        self.assertEqual(body["action_url"], "http://localhost:1620/sign")
        self.assertIn("digest", body["payload"])

    def test_unenabled_method_is_rejected(self):
        with override_settings(ESIGN_ENABLED_METHODS=["mock"]):
            response = self.initiate(signing_method="dsc")
        self.assert_error(response, errors.METHOD_NOT_ENABLED)

    def test_complete_verifies_embeds_and_stores(self):
        transaction = self.create_transaction(provider="dsc")
        pkcs7 = self._signed_pkcs7(transaction)

        response = self.client.post(
            reverse("esign-complete", args=[transaction.pk]), {"pkcs7": pkcs7}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["status"], ESignStatus.SUCCESS.value)
        self.assertTrue(body["signed_file_id"])

        transaction.refresh_from_db()
        self.assertEqual(transaction.status, ESignStatus.SUCCESS.value)
        self.assertEqual(len(self.pdf.embed_calls), 1)
        # Certificate metadata is audited; the blob is not.
        self.assertIn("certificate_fingerprint", transaction.response_audit)

    def test_complete_rejects_a_signature_for_another_document(self):
        transaction = self.create_transaction(provider="dsc")
        signer = make_signer()
        wrong = detached_cms(signer, b"\x00" * 32).dump()
        response = self.client.post(
            reverse("esign-complete", args=[transaction.pk]),
            {"pkcs7": base64.b64encode(wrong).decode()},
            format="json",
        )
        self.assert_error(response, errors.CLIENT_SIGNATURE_MISMATCH)
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, ESignStatus.FAILURE.value)

    def test_complete_rejects_empty_signature(self):
        transaction = self.create_transaction(provider="dsc")
        response = self.client.post(
            reverse("esign-complete", args=[transaction.pk]), {"pkcs7": ""}, format="json"
        )
        self.assert_error(response, errors.CLIENT_SIGNATURE_MISSING)

    def test_garbage_signature_returns_4xx_and_does_not_stick_in_signing(self):
        """A malformed CMS is a client error; the row must never be left SIGNING."""
        transaction = self.create_transaction(provider="dsc")
        response = self.client.post(
            reverse("esign-complete", args=[transaction.pk]),
            {"pkcs7": base64.b64encode(b"not a CMS at all").decode()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, ESignStatus.FAILURE.value)

    def test_provider_bug_marks_failure_not_stuck_in_signing(self):
        """An unexpected provider exception fails the row rather than stranding it."""
        transaction = self.create_transaction(provider="dsc")
        pkcs7 = self._signed_pkcs7(transaction)
        target = "addon.dsc_esign.provider.DSCESignProvider.verify_client_signature"
        with patch(target, side_effect=RuntimeError("boom")):
            response = self.client.post(
                reverse("esign-complete", args=[transaction.pk]), {"pkcs7": pkcs7}, format="json"
            )
        self.assertEqual(response.status_code, 400)
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, ESignStatus.FAILURE.value)

    def test_complete_refuses_a_callback_provider_transaction(self):
        transaction = self.create_transaction(provider="mock")
        pkcs7 = self._signed_pkcs7(transaction)
        response = self.client.post(
            reverse("esign-complete", args=[transaction.pk]), {"pkcs7": pkcs7}, format="json"
        )
        self.assert_error(response, errors.TRANSACTION_NOT_PROCESSABLE)

    def test_complete_requires_authentication(self):
        transaction = self.create_transaction(provider="dsc")
        self.client.force_authenticate(user=None)
        response = self.client.post(
            reverse("esign-complete", args=[transaction.pk]),
            {"pkcs7": "AA=="},
            format="json",
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_anonymous_callback_never_completes_a_dsc_transaction(self):
        transaction = self.create_transaction(provider="dsc")
        self.client.force_authenticate(user=None)
        response = self.post_callback(transaction)
        # The single CALLBACK provider (mock) cannot find a dsc-owned row.
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, ESignStatus.PENDING.value)

    def test_methods_endpoint_lists_enabled_methods(self):
        body = self.client.get(reverse("esign-methods")).json()
        methods = {m["method"]: m["completion"] for m in body["methods"]}
        self.assertEqual(methods.get("dsc"), "CLIENT_SIGNATURE")
        self.assertEqual(methods.get("mock"), "CALLBACK")
