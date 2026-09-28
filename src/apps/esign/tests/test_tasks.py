"""Maintenance task tests (spec 0015 #9)."""

from datetime import timedelta

from django.test import override_settings
from django.utils import timezone

from apps.esign.constants import ESIGN_SIGNING_INTERRUPTED, ESignStatus
from apps.esign.exceptions import ESignFileStorageError
from apps.esign.models import ESignTransaction
from apps.esign.tasks import (
    cleanup_placeholders,
    expire_stale_transactions,
    reconcile_signing_transactions,
)

from .base import ESignTestCase


def age(transaction, delta: timedelta):
    """Back-date ``updated_at`` past a sweeper threshold."""

    ESignTransaction.objects.filter(pk=transaction.pk).update(updated_at=timezone.now() - delta)


class ExpirySweeperTests(ESignTestCase):
    """``expire_stale_transactions``."""

    def test_pending_past_ttl_and_grace_is_expired(self):
        """The common real-world outcome is an abandoned C-DAC screen."""
        stale = self.create_transaction(
            provider_transaction_id="orders-stale",
            expires_at=timezone.now() - timedelta(seconds=3600),
        )

        self.assertEqual(expire_stale_transactions(), 1)

        stale.refresh_from_db()
        self.assertEqual(stale.status, ESignStatus.EXPIRED.value)
        self.assertTrue(stale.is_retryable)
        # Nothing failed, so no failure code is invented.
        self.assertEqual(stale.failure_code, "")

    def test_transactions_inside_the_grace_period_are_left_alone(self):
        """A callback may still arrive during the grace period."""
        fresh = self.create_transaction(
            provider_transaction_id="orders-fresh",
            expires_at=timezone.now() - timedelta(seconds=60),
        )

        self.assertEqual(expire_stale_transactions(), 0)
        fresh.refresh_from_db()
        self.assertEqual(fresh.status, ESignStatus.PENDING.value)

    def test_terminal_transactions_are_untouched(self):
        """Only PENDING rows expire."""
        done = self.create_transaction(provider_transaction_id="orders-done")
        self.post_callback(done)
        ESignTransaction.objects.filter(pk=done.pk).update(
            expires_at=timezone.now() - timedelta(seconds=3600)
        )

        self.assertEqual(expire_stale_transactions(), 0)
        done.refresh_from_db()
        self.assertEqual(done.status, ESignStatus.SUCCESS.value)

    def test_running_twice_changes_nothing_extra(self):
        """The sweeper is idempotent."""
        self.create_transaction(
            provider_transaction_id="orders-stale",
            expires_at=timezone.now() - timedelta(seconds=3600),
        )
        self.assertEqual(expire_stale_transactions(), 1)
        self.assertEqual(expire_stale_transactions(), 0)

    def test_task_can_be_enqueued(self):
        """The actor is registered with the broker."""
        message = expire_stale_transactions.send()
        self.assertEqual(message.actor_name, "expire_stale_transactions")


class ReconciliationTests(ESignTestCase):
    """``reconcile_signing_transactions``."""

    def test_stuck_signing_row_is_failed_for_retry(self):
        """A crashed worker leaves SIGNING; the retry path resolves it."""
        stuck = self.create_transaction(provider_transaction_id="orders-stuck")
        stuck.mark_signing()
        age(stuck, timedelta(seconds=3600))

        self.assertEqual(reconcile_signing_transactions(), 1)

        stuck.refresh_from_db()
        self.assertEqual(stuck.status, ESignStatus.FAILURE.value)
        self.assertEqual(stuck.failure_code, ESIGN_SIGNING_INTERRUPTED)
        self.assertTrue(stuck.placeholder_file_id)

    def test_recent_signing_rows_are_left_alone(self):
        """A callback still being processed must not be failed."""
        in_progress = self.create_transaction(provider_transaction_id="orders-inflight")
        in_progress.mark_signing()

        self.assertEqual(reconcile_signing_transactions(), 0)
        in_progress.refresh_from_db()
        self.assertEqual(in_progress.status, ESignStatus.SIGNING.value)


class PlaceholderCleanupTests(ESignTestCase):
    """``cleanup_placeholders``."""

    @override_settings(ESIGN_PLACEHOLDER_RETENTION=7)
    def test_old_terminal_placeholders_are_deleted_and_forgotten(self):
        """Only the intermediate prepared document is cleaned up."""
        transaction = self.create_transaction(provider_transaction_id="orders-old")
        self.post_callback(transaction)
        transaction.refresh_from_db()
        placeholder_file_id = transaction.placeholder_file_id
        signed_file_id = transaction.signed_file_id
        age(transaction, timedelta(days=30))

        self.assertEqual(cleanup_placeholders(), 1)

        transaction.refresh_from_db()
        self.assertEqual(transaction.placeholder_file_id, "")
        self.assertEqual(self.files.deleted, [placeholder_file_id])
        # Source and signed documents are never deleted.
        self.assertIn(signed_file_id, self.files.storage)
        self.assertIn(self.source_file_id, self.files.storage)

    def test_recent_and_pending_transactions_keep_their_placeholder(self):
        """Retention and terminality both gate the cleanup."""
        pending = self.create_transaction(provider_transaction_id="orders-pending")
        age(pending, timedelta(days=30))
        recent = self.create_transaction(provider_transaction_id="orders-recent")
        recent.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")

        self.assertEqual(cleanup_placeholders(), 0)
        self.assertEqual(self.files.deleted, [])

    def test_storage_failure_keeps_the_id_for_the_next_run(self):
        """A file that may still exist is never silently forgotten."""
        transaction = self.create_transaction(provider_transaction_id="orders-err")
        transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        age(transaction, timedelta(days=30))
        self.files.fail_delete = ESignFileStorageError()

        self.assertEqual(cleanup_placeholders(), 0)
        transaction.refresh_from_db()
        self.assertTrue(transaction.placeholder_file_id)

    def test_already_deleted_placeholder_is_forgotten(self):
        """A placeholder that is already gone must still be cleared."""
        transaction = self.create_transaction(provider_transaction_id="orders-gone")
        transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        age(transaction, timedelta(days=30))
        self.files.delete(transaction.placeholder_file_id)

        self.assertEqual(cleanup_placeholders(), 1)
        transaction.refresh_from_db()
        self.assertEqual(transaction.placeholder_file_id, "")
