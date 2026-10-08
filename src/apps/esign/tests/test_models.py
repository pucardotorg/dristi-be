"""Model, state machine and constraint tests (spec 0015 #5)."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from django.utils import timezone

from apps.esign.constants import EntityType, ESignStatus
from apps.esign.exceptions import ESignInvalidTransition
from apps.esign.models import ESignTransaction

from .base import PLACEHOLDER, registered_user


def build(**overrides):
    """Return an unsaved transaction with sensible defaults."""

    fields = {
        "module": "orders",
        "entity_type": EntityType.ORDER.value,
        "entity_id": "9f2c",
        "provider": "mock",
        "provider_transaction_id": "orders-1",
        "source_file_id": "source-1",
        "placeholder_file_id": "placeholder-1",
        "sign_placeholder": dict(PLACEHOLDER),
        "document_hash": "ab12",
        "signature_field_name": "Signature1",
        "expires_at": timezone.now() + timedelta(seconds=900),
    }
    fields.update(overrides)
    return ESignTransaction(**fields)


class TransitionTests(TestCase):
    """Legal and illegal transitions."""

    def test_pending_to_signing_to_success(self):
        """The happy path walks PENDING -> SIGNING -> SUCCESS."""
        transaction_row = build()
        transaction_row.save()

        transaction_row.mark_signing()
        self.assertEqual(transaction_row.status, ESignStatus.SIGNING.value)
        self.assertIsNotNone(transaction_row.callback_received_at)

        transaction_row.mark_success(signed_file_id="signed-1")
        self.assertEqual(transaction_row.status, ESignStatus.SUCCESS.value)
        self.assertEqual(transaction_row.signed_file_id, "signed-1")
        self.assertIsNotNone(transaction_row.completed_at)

    def test_success_is_terminal(self):
        """No transition leaves SUCCESS."""
        row = build()
        row.save()
        row.mark_signing()
        row.mark_success(signed_file_id="signed-1")

        for attempt in (
            lambda: row.mark_signing(),
            lambda: row.mark_failed("ESIGN_PDF_EMBED_FAILED"),
            lambda: row.mark_expired(),
        ):
            with self.assertRaises(ESignInvalidTransition):
                attempt()

    def test_failure_and_expiry_never_transition(self):
        """FAILURE and EXPIRED are dead ends; a retry creates a new row."""
        failed = build(provider_transaction_id="orders-2")
        failed.save()
        failed.mark_failed("ESIGN_PROVIDER_REJECTED", "rejected")
        with self.assertRaises(ESignInvalidTransition):
            failed.mark_signing()

        expired = build(provider_transaction_id="orders-3")
        expired.save()
        expired.mark_expired(message="no callback")
        with self.assertRaises(ESignInvalidTransition):
            expired.mark_failed("ESIGN_PROVIDER_REJECTED")

    def test_signing_only_from_pending(self):
        """SIGNING is only enterable from PENDING."""
        row = build()
        row.save()
        row.mark_signing()
        with self.assertRaises(ESignInvalidTransition):
            row.mark_signing()

    def test_success_requires_a_signed_file_id(self):
        """mark_success refuses to complete without the stored artefact."""
        row = build()
        row.save()
        row.mark_signing()
        with self.assertRaises(ESignInvalidTransition):
            row.mark_success(signed_file_id="")

    def test_failure_keeps_the_placeholder(self):
        """A failure retains the prepared document for a retry."""
        row = build()
        row.save()
        row.mark_failed("ESIGN_PDF_EMBED_FAILED", "embed failed")
        row.refresh_from_db()
        self.assertEqual(row.placeholder_file_id, "placeholder-1")
        self.assertTrue(row.is_retryable)


class ConstraintTests(TestCase):
    """Database-level guarantees."""

    def test_provider_transaction_id_is_unique_per_provider(self):
        """The (provider, provider_transaction_id) pair is the real identity."""
        build(provider_transaction_id="orders-1").save()
        with transaction.atomic(), self.assertRaises(IntegrityError):
            build(provider_transaction_id="orders-1").save()

        # The same id issued by a different ESP is a different transaction.
        build(provider="other", provider_transaction_id="orders-1").save()

    def test_unassigned_provider_transaction_ids_do_not_collide(self):
        """Rows whose ESP id was never assigned are not each other's duplicates."""
        build(provider_transaction_id="").save()
        build(provider_transaction_id="").save()
        self.assertEqual(ESignTransaction.objects.filter(provider_transaction_id="").count(), 2)

    def test_success_without_signed_file_is_rejected_by_the_database(self):
        """The SUCCESS/signed_file_id invariant is enforced in SQL."""
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ESignTransaction.objects.create(
                module="orders",
                provider="mock",
                provider_transaction_id="orders-9",
                source_file_id="source-1",
                placeholder_file_id="placeholder-1",
                status=ESignStatus.SUCCESS.value,
                expires_at=timezone.now(),
            )

    def test_signing_without_placeholder_is_rejected_by_the_database(self):
        """A row being signed must have a prepared document to sign."""
        with transaction.atomic(), self.assertRaises(IntegrityError):
            ESignTransaction.objects.create(
                module="orders",
                provider="mock",
                provider_transaction_id="orders-10",
                source_file_id="source-1",
                placeholder_file_id="",
                status=ESignStatus.SIGNING.value,
                expires_at=timezone.now(),
            )


class ModelInvariantTests(TestCase):
    """``clean()`` invariants and field semantics."""

    def test_organization_id_is_optional(self):
        """Not every signed document is organization scoped."""
        row = build(organization_id=None)
        row.full_clean()
        row.save()
        self.assertIsNone(row.organization_id)

    def test_entity_type_choices_are_bounded(self):
        """entity_type is an enum, not a free string."""
        row = build(entity_type="INVOICE")
        with self.assertRaises(ValidationError):
            row.full_clean()

    def test_hash_must_be_lowercase_hex(self):
        """A hash that is not a hex digest is refused."""
        with self.assertRaises(ValidationError) as caught:
            build(document_hash="ZZZZ").clean()
        self.assertIn("document_hash", caught.exception.message_dict)

    def test_placeholder_geometry_is_validated(self):
        """Negative and non-numeric placement values are refused."""
        for placeholder in (
            {**PLACEHOLDER, "x": -1},
            {**PLACEHOLDER, "width": 0},
            {**PLACEHOLDER, "height": "tall"},
            {**PLACEHOLDER, "page": 1.5},
        ):
            with self.assertRaises(ValidationError):
                build(sign_placeholder=placeholder).clean()

    def test_signer_is_protected(self):
        """A signer cannot be deleted out from under the audit trail."""
        user = registered_user()
        row = build(signer=user)
        row.save()
        with self.assertRaises(ProtectedError):
            user.delete()

    def test_default_ordering_is_newest_first(self):
        """Meta.ordering keeps list behaviour predictable."""
        first = build(provider_transaction_id="orders-a")
        first.save()
        second = build(provider_transaction_id="orders-b")
        second.save()
        self.assertEqual(
            [row.provider_transaction_id for row in ESignTransaction.objects.all()],
            ["orders-b", "orders-a"],
        )
