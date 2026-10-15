"""Security tests (spec 0015 #12, #14)."""

import logging

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from apps.esign.constants import ESignStatus
from apps.esign.models import ESignTransaction

from .base import PKCS7_BASE64, ESignTestCase, registered_user


class CallbackTargetingTests(ESignTestCase):
    """A callback can never choose which document gets signed."""

    def setUp(self):
        """Create two transactions belonging to different documents."""
        super().setUp()
        self.target = self.create_transaction(provider_transaction_id="orders-target")
        self.other_source = self.files.add(b"%PDF-other\n%%EOF\n")
        self.other = self.create_transaction(
            provider_transaction_id="orders-other",
            source_file_id=self.other_source,
        )
        self.client.force_authenticate(user=None)

    def test_request_supplied_file_ids_are_ignored(self):
        """The documents come from the stored row, never from the request."""
        self.post_callback(
            self.target,
            file_id=self.other_source,
            placeholder_file_id=self.other.placeholder_file_id,
            signed_file_id="attacker-chosen",
            transaction_id=str(self.other.pk),
        )

        self.target.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.target.status, ESignStatus.SUCCESS.value)
        self.assertNotEqual(self.target.signed_file_id, "attacker-chosen")
        self.assertEqual(self.other.status, ESignStatus.PENDING.value)

        embedded_document = self.pdf.embed_calls[0][0]
        self.assertEqual(embedded_document, self.files.content_of(self.target.placeholder_file_id))

    def test_a_successful_transaction_cannot_be_re_signed(self):
        """SUCCESS is terminal; a replay produces no second signature."""
        self.post_callback(self.target)
        self.target.refresh_from_db()
        first_signed = self.target.signed_file_id

        self.post_callback(self.target)

        self.target.refresh_from_db()
        self.assertEqual(self.target.signed_file_id, first_signed)
        self.assertEqual(len(self.pdf.embed_calls), 1)

    @override_settings(ESIGN_UI_REDIRECT_URL="https://ui.example.org/return")
    def test_redirect_target_cannot_be_influenced_by_the_request(self):
        """Taking the target from the request would be an open redirect."""
        response = self.client.post(
            reverse("esign-callback"),
            {
                **self.callback_payload(self.target),
                "redirect_url": "https://evil.example.com/steal",
                "next": "https://evil.example.com/steal",
                "responseUrl": "https://evil.example.com/steal",
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertTrue(response["Location"].startswith("https://ui.example.org/return?"))
        self.assertNotIn("evil.example.com", response["Location"])

    def test_rejected_callbacks_do_not_redirect(self):
        """An unverified caller is never handed a redirect to follow."""
        response = self.client.post(
            reverse("esign-callback"),
            {"txn": "orders-unknown", "status": "1", "signature": PKCS7_BASE64},
            format="multipart",
        )
        self.assertNotIn("Location", response)


class ScopingTests(ESignTestCase):
    """One user cannot read or retry another user's transaction."""

    def setUp(self):
        """Create a transaction for the signer and sign in as someone else."""
        super().setUp()
        self.transaction = self.create_transaction()
        self.transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        self.client.force_authenticate(user=registered_user("+919812345678"))

    def test_status_is_scoped_to_the_signer(self):
        """Another user's transaction is not found, not forbidden."""
        response = self.client.get(reverse("esign-transaction", args=[self.transaction.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retry_is_scoped_to_the_signer(self):
        """Another user cannot start an attempt on someone else's document."""
        response = self.client.post(reverse("esign-retry", args=[self.transaction.pk]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ESignTransaction.objects.count(), 1)


class SecretHandlingTests(ESignTestCase):
    """Key material, signatures and document bytes never leak."""

    def test_signature_bytes_are_not_stored_on_the_transaction(self):
        """Neither the PKCS#7 blob nor the raw callback body is persisted."""
        transaction = self.create_transaction()
        self.post_callback(transaction)

        transaction.refresh_from_db()
        row = str(transaction.__dict__)
        self.assertNotIn(PKCS7_BASE64, row)
        self.assertNotIn("%PDF", row)

    def test_response_body_carries_no_signature_or_document_bytes(self):
        """API responses expose ids and statuses only."""
        initiated = self.initiate()
        transaction = ESignTransaction.objects.get()
        self.post_callback(transaction)
        statused = self.client.get(reverse("esign-transaction", args=[transaction.pk]))

        for body in (initiated.content, statused.content):
            self.assertNotIn(b"%PDF", body)
            self.assertNotIn(PKCS7_BASE64.encode(), body)

    def test_logs_carry_no_document_or_signature_bytes(self):
        """Structured log lines carry correlation fields, not content."""
        transaction = self.create_transaction()
        with self.assertLogs("apps.esign", level=logging.INFO) as captured:
            self.post_callback(transaction)

        joined = "\n".join(captured.output)
        self.assertIn("event='ESIGN_SUCCEEDED'", joined)
        self.assertNotIn(PKCS7_BASE64, joined)
        self.assertNotIn("%PDF", joined)
