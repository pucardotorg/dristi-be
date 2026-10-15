"""Callback service tests (spec 0015 #8, #14)."""

import logging
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.esign.clients.pdf import prepared_document_max_bytes
from apps.esign.constants import (
    ESIGN_PDF_EMBED_FAILED,
    ESIGN_PROVIDER_REJECTED,
    ESIGN_SIGNATURE_MISSING,
    ESIGN_SIGNED_UPLOAD_FAILED,
    ESIGN_SIGNING_INTERRUPTED,
    ESignStatus,
)
from apps.esign.exceptions import (
    ESignCallbackMalformed,
    ESignFileStorageError,
    ESignNotProcessable,
    ESignPDFEmbedError,
    ESignResponseStale,
    ESignResponseUntrusted,
    ESignSignatureInvalid,
    ESignSignedUploadError,
    ESignTransactionNotFound,
)
from apps.esign.models import ESignTransaction
from apps.esign.services import (
    process_callback,
    reconcile_signing_transactions,
    retry_transaction,
)

from .base import PKCS7_BLOB, ESignTestCase
from .fakes import SIGNED_MARKER


class CallbackTests(ESignTestCase):
    """Verification, gating and completion."""

    def setUp(self):
        """Start from a PENDING transaction awaiting its callback."""
        super().setUp()
        self.transaction = self.create_transaction()

    def test_successful_callback_stores_a_signed_pdf(self):
        """The signature is embedded and the signed PDF stored as a new file."""
        outcome = process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        self.assertEqual(outcome.status, ESignStatus.SUCCESS.value)
        self.assertEqual(self.transaction.status, ESignStatus.SUCCESS.value)
        self.assertTrue(self.transaction.signed_file_id)
        self.assertIsNotNone(self.transaction.completed_at)
        self.assertIsNotNone(self.transaction.callback_received_at)

        signed = self.files.content_of(self.transaction.signed_file_id)
        self.assertIn(SIGNED_MARKER + PKCS7_BLOB, signed)
        self.assertEqual(self.files.uploads[-1]["file_type"], "DIGITALLY_SIGNED")

    def test_signed_upload_is_attributed_to_the_signer(self):
        """The callback leg has no request user, so the stored signer is the actor."""
        process_callback(self.callback_payload(self.transaction))
        self.assertEqual(self.files.uploads[-1]["user_id"], str(self.user.pk))

    @override_settings(ESIGN_SYSTEM_ACTOR_ID="system-actor")
    def test_signed_upload_falls_back_to_the_system_actor(self):
        """A transaction without a signer records the configured system actor."""
        transaction = self.create_transaction(signer=None, provider_transaction_id="orders-sys")
        process_callback(self.callback_payload(transaction))
        self.assertEqual(self.files.uploads[-1]["user_id"], "system-actor")

    def test_unknown_transaction_is_rejected(self):
        """A verified response that correlates to nothing is rejected."""
        with self.assertRaises(ESignTransactionNotFound):
            process_callback({"txn": "orders-unknown", "status": "1", "signature": "Zm9v"})

    def test_malformed_payload_is_rejected(self):
        """A payload with no transaction id cannot be processed."""
        with self.assertRaises(ESignCallbackMalformed):
            process_callback({"status": "1"})

    def test_untrusted_response_is_rejected_before_any_lookup(self):
        """Verification failure stops processing; nothing is recorded."""
        with patch(
            "apps.esign.providers.mock.MockESignProvider.verify_response",
            side_effect=ESignResponseUntrusted(),
        ):
            with self.assertRaises(ESignResponseUntrusted):
                process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.PENDING.value)
        self.assertEqual(self.pdf.embed_calls, [])

    def test_stale_response_is_rejected_by_the_provider(self):
        """A response outside the ESP skew window never reaches the row."""
        with patch(
            "apps.esign.providers.mock.MockESignProvider.verify_response",
            side_effect=ESignResponseStale(),
        ):
            with self.assertRaises(ESignResponseStale):
                process_callback(self.callback_payload(self.transaction))

    def test_callback_after_the_grace_period_expires_the_transaction(self):
        """A late callback is refused and the row is closed as EXPIRED."""
        self.transaction.expires_at = timezone.now() - timedelta(seconds=3600)
        self.transaction.save(update_fields=["expires_at"])

        with self.assertRaises(ESignResponseStale):
            process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.EXPIRED.value)
        self.assertEqual(self.pdf.embed_calls, [])

    def test_provider_rejection_is_recorded_as_a_failure(self):
        """An ESP failure closes the transaction with a safe message."""
        outcome = process_callback(
            self.callback_payload(
                self.transaction, status="0", signature=None, errCode="E7", errMsg="user cancelled"
            )
        )

        self.transaction.refresh_from_db()
        self.assertEqual(outcome.status, ESignStatus.FAILURE.value)
        self.assertEqual(self.transaction.failure_code, ESIGN_PROVIDER_REJECTED)
        self.assertEqual(self.transaction.response_audit["error_code"], "E7")
        self.assertEqual(self.transaction.response_audit["error_message"], "user cancelled")
        self.assertEqual(self.pdf.embed_calls, [])
        # The placeholder is retained so the user can retry.
        self.assertTrue(self.transaction.placeholder_file_id)

    def test_success_without_a_signature_is_a_failure(self):
        """A success that carries no signature cannot produce a signed PDF."""
        outcome = process_callback(self.callback_payload(self.transaction, signature=None))

        self.transaction.refresh_from_db()
        self.assertEqual(outcome.status, ESignStatus.FAILURE.value)
        self.assertEqual(self.transaction.failure_code, ESIGN_SIGNATURE_MISSING)

    def test_non_base64_signature_is_a_failure(self):
        """A signature that cannot be decoded is recorded as invalid."""
        with self.assertRaises(ESignSignatureInvalid):
            process_callback(self.callback_payload(self.transaction, signature="not base64!!"))

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.FAILURE.value)

    def test_placeholder_read_failure_is_recorded(self):
        """Losing the prepared document is a recorded failure, not a crash."""
        self.files.fail_get_content = ESignFileStorageError()
        with self.assertRaises(ESignFileStorageError):
            process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.FAILURE.value)

    def test_embed_failure_is_recorded(self):
        """An embedding failure closes the transaction with its own code."""
        self.pdf.fail_embed = ESignPDFEmbedError()
        with self.assertRaises(ESignPDFEmbedError):
            process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.FAILURE.value)
        self.assertEqual(self.transaction.failure_code, ESIGN_PDF_EMBED_FAILED)

    def test_signed_upload_failure_is_recorded(self):
        """A storage failure after embedding is its own failure code."""
        self.files.fail_upload = ESignFileStorageError()
        with self.assertRaises(ESignSignedUploadError):
            process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.FAILURE.value)
        self.assertEqual(self.transaction.failure_code, ESIGN_SIGNED_UPLOAD_FAILED)
        self.assertEqual(self.transaction.signed_file_id, "")

    def test_duplicate_callback_does_not_sign_twice(self):
        """A replayed delivery is a no-op that reports the same outcome."""
        first = process_callback(self.callback_payload(self.transaction))
        signed_file_id = first.transaction.signed_file_id

        second = process_callback(self.callback_payload(self.transaction))

        self.assertEqual(second.status, ESignStatus.SUCCESS.value)
        self.assertEqual(second.transaction.signed_file_id, signed_file_id)
        self.assertEqual(len(self.pdf.embed_calls), 1)

    def test_callback_for_a_transaction_in_progress_is_not_reprocessed(self):
        """A row another worker holds is answered without more work."""
        self.transaction.mark_signing()

        outcome = process_callback(self.callback_payload(self.transaction))

        self.assertEqual(outcome.status, ESignStatus.SIGNING.value)
        self.assertEqual(self.pdf.embed_calls, [])

    def test_callback_for_a_failed_transaction_is_rejected(self):
        """A dead-end row is not resurrected by a late callback."""
        self.transaction.mark_failed(ESIGN_PROVIDER_REJECTED, "rejected")

        with self.assertRaises(ESignNotProcessable):
            process_callback(self.callback_payload(self.transaction))

    def test_response_audit_never_holds_the_signature(self):
        """Codes and metadata only: the PKCS#7 blob is never persisted."""
        process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        serialised = str(self.transaction.response_audit)
        self.assertNotIn("signature'", serialised.replace("signature_count", ""))
        self.assertNotIn(PKCS7_BLOB.hex(), serialised)

    @override_settings(PDF_MAX_SIGN_INPUT_BYTES=1000, PDF_SIGNATURE_CONTAINER_BYTES=100)
    def test_placeholder_is_read_with_room_for_the_signature_container(self):
        """A source accepted at the limit must not be rejected as a placeholder.

        The prepared document is the source plus the reserved container, so
        reading it under the source limit would fail after the signer's OTP.
        """
        process_callback(self.callback_payload(self.transaction))

        reads = dict(self.files.content_reads)
        limit = reads[self.transaction.placeholder_file_id]
        self.assertEqual(limit, prepared_document_max_bytes())
        self.assertGreater(limit, 1000 + 2 * 100)


class CompletionCompareAndSetTests(ESignTestCase):
    """Completion only succeeds if the row is still SIGNING when it commits."""

    def setUp(self):
        """Start from a PENDING transaction awaiting its callback."""
        super().setUp()
        self.transaction = self.create_transaction()

    def reconcile_during_upload(self):
        """Make the stuck-SIGNING reconciler win the race during the upload."""
        original_upload = self.files.upload

        def upload_then_reconcile(*args, **kwargs):
            file_id = original_upload(*args, **kwargs)
            # Far enough in the future that the row counts as stuck.
            reconcile_signing_transactions(now=timezone.now() + timedelta(hours=1))
            return file_id

        self.files.upload = upload_then_reconcile

    def test_a_reconciled_row_is_not_resurrected_as_success(self):
        """FAILURE is a dead end; a late completion must not overwrite it."""
        self.reconcile_during_upload()

        with self.assertLogs("apps.esign", level=logging.WARNING) as captured:
            outcome = process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.status, ESignStatus.FAILURE.value)
        self.assertEqual(self.transaction.failure_code, ESIGN_SIGNING_INTERRUPTED)
        self.assertEqual(self.transaction.signed_file_id, "")
        self.assertEqual(outcome.status, ESignStatus.FAILURE.value)

        # Support can locate the signed PDF that no transaction now owns.
        orphan = self.files.uploads[-1]["id"]
        self.assertIn(f"orphaned_signed_file_id={orphan!r}", "\n".join(captured.output))

    def test_a_reconciled_row_stays_retryable_without_a_live_sibling(self):
        """The retry the user starts after reconciliation is the only live attempt."""
        self.reconcile_during_upload()
        process_callback(self.callback_payload(self.transaction))

        self.transaction.refresh_from_db()
        result = retry_transaction(self.transaction, user=self.user)

        self.assertEqual(result.transaction.status, ESignStatus.PENDING.value)
        self.assertEqual(
            ESignTransaction.objects.filter(status=ESignStatus.SUCCESS.value).count(), 0
        )
