"""End-to-end flow, duplicate and concurrent callbacks, retry (spec 0015 #14)."""

from unittest.mock import patch

from django.test import override_settings
from django.urls import reverse
from rest_framework import status

from apps.esign.constants import (
    ESIGN_MAX_ATTEMPTS_EXCEEDED,
    ESIGN_NOT_RETRYABLE,
    ESignStatus,
)
from apps.esign.models import ESignTransaction
from apps.esign.providers import get_provider
from apps.esign.services import process_callback

from .base import PKCS7_BLOB, SOURCE_PDF, ESignTestCase
from .fakes import PREPARED_MARKER, SIGNED_MARKER


class FullFlowTests(ESignTestCase):
    """Initiate, sign, and read the outcome back."""

    def test_initiate_then_callback_produces_a_signed_document(self):
        """The documented three-legged flow completes."""
        initiated = self.initiate().json()
        transaction = ESignTransaction.objects.get(pk=initiated["transaction_id"])

        self.client.force_authenticate(user=None)
        callback = self.post_callback(transaction)
        self.assertIn(callback.status_code, (status.HTTP_200_OK, status.HTTP_302_FOUND))

        transaction.refresh_from_db()
        self.assertEqual(transaction.status, ESignStatus.SUCCESS.value)
        self.assertTrue(transaction.signed_file_id)

        self.client.force_authenticate(user=self.user)
        payload = self.client.get(reverse("esign-transaction", args=[transaction.pk])).json()
        self.assertEqual(payload["status"], ESignStatus.SUCCESS.value)
        self.assertEqual(payload["signed_file_id"], transaction.signed_file_id)

    def test_source_document_is_byte_identical_afterwards(self):
        """Signing never mutates the source; every artefact is a new file."""
        initiated = self.initiate().json()
        transaction = ESignTransaction.objects.get(pk=initiated["transaction_id"])
        self.post_callback(transaction)
        transaction.refresh_from_db()

        self.assertEqual(self.files.content_of(self.source_file_id), SOURCE_PDF)
        self.assertEqual(
            self.files.content_of(transaction.placeholder_file_id),
            SOURCE_PDF + PREPARED_MARKER,
        )
        self.assertEqual(
            self.files.content_of(transaction.signed_file_id),
            SOURCE_PDF + PREPARED_MARKER + SIGNED_MARKER + PKCS7_BLOB,
        )
        self.assertNotEqual(transaction.signed_file_id, transaction.placeholder_file_id)
        self.assertNotEqual(transaction.signed_file_id, transaction.source_file_id)

    @override_settings(ESIGN_UI_REDIRECT_URL="https://ui.example.org/return")
    def test_duplicate_delivery_produces_no_second_signed_file(self):
        """A replayed callback returns the same redirect and signs once."""
        transaction = self.create_transaction()
        first = self.post_callback(transaction)
        second = self.post_callback(transaction)

        self.assertEqual(first["Location"], second["Location"])
        self.assertEqual(len(self.pdf.embed_calls), 1)
        self.assertEqual(
            ESignTransaction.objects.filter(status=ESignStatus.SUCCESS.value).count(), 1
        )

    def test_concurrent_callbacks_embed_exactly_once(self):
        """The second caller observes SIGNING and does no work of its own.

        The race is reproduced deterministically: the second delivery arrives
        while the first is between its two database transactions, which is the
        exact window ``SIGNING`` exists to guard.
        """
        transaction = self.create_transaction()
        outcomes = []
        payload = self.callback_payload(transaction)
        original_embed = self.pdf.embed_signature

        def embed_while_a_second_callback_arrives(*args, **kwargs):
            outcomes.append(process_callback(payload))
            return original_embed(*args, **kwargs)

        self.pdf.embed_signature = embed_while_a_second_callback_arrives
        process_callback(payload)

        self.assertEqual(len(self.pdf.embed_calls), 1)
        self.assertEqual([outcome.status for outcome in outcomes], [ESignStatus.SIGNING.value])
        transaction.refresh_from_db()
        self.assertEqual(transaction.status, ESignStatus.SUCCESS.value)


class RetryFlowTests(ESignTestCase):
    """Retry chains and the attempt budget."""

    def test_retry_chain_reuses_the_placeholder(self):
        """Each attempt is its own row; the prepared document is prepared once."""
        first = self.create_transaction()
        first.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        prepare_calls = len(self.pdf.prepare_calls)

        retry = self.client.post(reverse("esign-retry", args=[first.pk])).json()
        second = ESignTransaction.objects.get(pk=retry["transaction_id"])

        self.assertEqual(len(self.pdf.prepare_calls), prepare_calls)
        self.assertEqual(second.placeholder_file_id, first.placeholder_file_id)
        self.assertEqual(second.retry_of, first)

    @override_settings(ESIGN_MAX_ATTEMPTS=3)
    def test_attempts_are_bounded(self):
        """The budget counts attempts across the whole chain."""
        transaction = self.create_transaction()
        for expected_attempt in (2, 3):
            transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
            response = self.client.post(reverse("esign-retry", args=[transaction.pk]))
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            transaction = ESignTransaction.objects.get(pk=response.json()["transaction_id"])
            self.assertEqual(transaction.attempt_count, expected_attempt)

        transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        exhausted = self.client.post(reverse("esign-retry", args=[transaction.pk]))
        self.assertEqual(exhausted.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retry_re_prepares_when_the_placeholder_is_gone(self):
        """A cleaned-up placeholder is rebuilt from the untouched source."""
        first = self.create_transaction()
        first.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        self.files.delete(first.placeholder_file_id)
        prepare_calls = len(self.pdf.prepare_calls)

        retry = self.client.post(reverse("esign-retry", args=[first.pk])).json()
        second = ESignTransaction.objects.get(pk=retry["transaction_id"])

        self.assertEqual(len(self.pdf.prepare_calls), prepare_calls + 1)
        self.assertNotEqual(second.placeholder_file_id, first.placeholder_file_id)
        self.assertTrue(second.document_hash)

    def test_retry_can_be_signed(self):
        """The new attempt is a fully working transaction."""
        first = self.create_transaction()
        first.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        retry = self.client.post(reverse("esign-retry", args=[first.pk])).json()
        second = ESignTransaction.objects.get(pk=retry["transaction_id"])

        self.post_callback(second)

        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(second.status, ESignStatus.SUCCESS.value)
        self.assertEqual(first.status, ESignStatus.FAILURE.value)


class PlaceholderRecoveryTests(ESignTestCase):
    """Retry when neither the prepared document nor the source is available."""

    def test_retry_without_placeholder_or_source_is_refused(self):
        """A document that cannot be rebuilt is reported on the new attempt.

        The attempt is claimed before the prepared document is rebuilt — the
        rebuild calls the PDF and File Storage services and must not run under
        the parent's row lock — so the failure is recorded on the claimed row
        like any other post-creation failure (spec 0015 #9).
        """
        from apps.esign.constants import ESIGN_PLACEHOLDER_MISSING

        transaction = self.create_transaction()
        transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        self.files.delete(transaction.placeholder_file_id)
        self.files.delete(transaction.source_file_id)

        response = self.client.post(reverse("esign-retry", args=[transaction.pk]))

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], ESIGN_PLACEHOLDER_MISSING)

        claimed = ESignTransaction.objects.get(retry_of=transaction)
        self.assertEqual(claimed.status, ESignStatus.FAILURE.value)
        self.assertEqual(claimed.failure_code, ESIGN_PLACEHOLDER_MISSING)
        self.assertEqual(claimed.provider_transaction_id, "")


class RetryBudgetTests(ESignTestCase):
    """An attempt may be retried once, so the budget cannot be walked around."""

    @override_settings(ESIGN_MAX_ATTEMPTS=3)
    def test_the_same_parent_cannot_be_retried_twice(self):
        """Sibling attempts would all claim the same attempt_count."""
        parent = self.create_transaction()
        parent.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        url = reverse("esign-retry", args=[parent.pk])

        first = self.client.post(url)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(url)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(second.json()["code"], ESIGN_NOT_RETRYABLE)
        self.assertEqual(parent.retries.count(), 1)

    @override_settings(ESIGN_MAX_ATTEMPTS=2)
    def test_hammering_one_parent_cannot_exceed_the_budget(self):
        """Ten retries of one dead attempt leave one live transaction."""
        parent = self.create_transaction()
        parent.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        url = reverse("esign-retry", args=[parent.pk])

        codes = {self.client.post(url).status_code for _ in range(10)}

        self.assertEqual(codes, {status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST})
        self.assertEqual(
            ESignTransaction.objects.filter(status=ESignStatus.PENDING.value).count(), 1
        )
        self.assertEqual(ESignTransaction.objects.count(), 2)

    @override_settings(ESIGN_MAX_ATTEMPTS=3)
    def test_concurrent_retries_create_exactly_one_attempt(self):
        """The second caller runs while the first is mid-retry and is refused.

        The race is reproduced deterministically by re-entering the service
        from inside the first call's provider step — after the row lock has
        been taken and the child created.
        """
        from apps.esign.exceptions import ESignError
        from apps.esign.services import retry_transaction

        parent = self.create_transaction()
        parent.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")

        provider = get_provider()
        original_build = provider.build_initiation
        refused = []

        def build_while_a_second_retry_arrives(*args, **kwargs):
            try:
                retry_transaction(parent, user=self.user)
            except ESignError as exc:
                refused.append(exc.code)
            return original_build(*args, **kwargs)

        with patch.object(provider, "build_initiation", build_while_a_second_retry_arrives):
            retry_transaction(parent, user=self.user)

        self.assertEqual(refused, [ESIGN_NOT_RETRYABLE])
        self.assertEqual(parent.retries.count(), 1)

    @override_settings(ESIGN_MAX_ATTEMPTS=3)
    def test_the_chain_is_walked_by_retrying_the_newest_attempt(self):
        """Each attempt advances the budget, and the chain stays linear."""
        transaction = self.create_transaction()
        chain = [transaction]
        for expected_attempt in (2, 3):
            transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
            payload = self.client.post(reverse("esign-retry", args=[transaction.pk])).json()
            transaction = ESignTransaction.objects.get(pk=payload["transaction_id"])
            self.assertEqual(transaction.attempt_count, expected_attempt)
            chain.append(transaction)

        transaction.mark_failed("ESIGN_PROVIDER_REJECTED", "refused")
        exhausted = self.client.post(reverse("esign-retry", args=[transaction.pk]))
        self.assertEqual(exhausted.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(exhausted.json()["code"], ESIGN_MAX_ATTEMPTS_EXCEEDED)
        self.assertEqual(
            [row.retry_of for row in chain[1:]],
            chain[:-1],
        )
