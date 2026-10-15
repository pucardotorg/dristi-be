"""Initiation service tests (spec 0015 #2, #9, #14)."""

from unittest.mock import patch

from django.test import override_settings

from apps.esign import permissions
from apps.esign.constants import (
    ESIGN_FILE_STORAGE_UNAVAILABLE,
    ESIGN_PDF_PREPARATION_FAILED,
    ESIGN_REQUEST_BUILD_FAILED,
    ESignStatus,
)
from apps.esign.exceptions import (
    ESignAlreadyInProgress,
    ESignDisabled,
    ESignFileStorageError,
    ESignInvalidPlaceholder,
    ESignNotAPDF,
    ESignNotPermitted,
    ESignPDFError,
    ESignRequestBuildFailed,
    ESignSourceNotFound,
)
from apps.esign.models import ESignTransaction
from apps.esign.providers.base import ESignInitiation
from apps.esign.services import initiate_esign

from .base import PLACEHOLDER, SOURCE_PDF, ESignTestCase
from .fakes import PREPARED_MARKER


class InitiationTests(ESignTestCase):
    """The happy path and every failure mode of initiation."""

    def initiate_service(self, **overrides):
        """Call the service directly with the standard arguments."""

        kwargs = {
            "user": self.user,
            "module": "orders",
            "file_id": self.source_file_id,
            "entity_type": "ORDER",
            "entity_id": "9f2c0001",
            "organization_id": None,
            "sign_placeholder": dict(PLACEHOLDER),
        }
        kwargs.update(overrides)
        return initiate_esign(**kwargs)

    def test_happy_path_creates_a_pending_transaction(self):
        """The document is prepared, stored, and a PENDING row is created."""
        result = self.initiate_service()
        transaction = result.transaction

        self.assertEqual(transaction.status, ESignStatus.PENDING.value)
        self.assertEqual(transaction.provider, "mock")
        self.assertEqual(transaction.signer, self.user)
        self.assertEqual(transaction.source_file_id, self.source_file_id)
        self.assertTrue(transaction.placeholder_file_id)
        self.assertEqual(transaction.signature_field_name, "Signature1")
        self.assertTrue(transaction.document_hash)
        self.assertEqual(transaction.sign_placeholder, PLACEHOLDER)
        self.assertGreater(transaction.expires_at, transaction.created_at)
        self.assertEqual(
            result.initiation.provider_transaction_id, transaction.provider_transaction_id
        )

    def test_source_document_is_never_modified(self):
        """The prepared PDF is a new file; the source is byte-identical."""
        result = self.initiate_service()

        self.assertEqual(self.files.content_of(self.source_file_id), SOURCE_PDF)
        self.assertEqual(
            self.files.content_of(result.transaction.placeholder_file_id),
            SOURCE_PDF + PREPARED_MARKER,
        )

    def test_placeholder_is_tagged_for_discovery(self):
        """Artefacts carry the esign, module and entity tags (#4.2)."""
        self.initiate_service()
        upload = self.files.uploads[0]

        self.assertEqual(upload["file_type"], "PDF")
        self.assertEqual(upload["tags"], ["esign", "orders", "9f2c0001"])
        self.assertEqual(upload["user_id"], str(self.user.pk))

    def test_placement_is_passed_through_to_the_pdf_adapter(self):
        """The adapter receives the caller's placement verbatim.

        Narrowing it to the keys 0016 accepts is the adapter's job and is
        covered in ``test_clients``.
        """
        self.initiate_service()
        self.assertEqual(self.pdf.prepare_calls, [PLACEHOLDER])

    @override_settings(ESIGN_ENABLED=False)
    def test_kill_switch_refuses_initiation(self):
        """Nothing is prepared or stored while eSign is off."""
        with self.assertRaises(ESignDisabled):
            self.initiate_service()
        self.assertEqual(ESignTransaction.objects.count(), 0)
        self.assertEqual(self.files.uploads, [])

    def test_missing_source_stores_nothing(self):
        """A failure before the row exists leaves no trace."""
        with self.assertRaises(ESignSourceNotFound):
            self.initiate_service(file_id="does-not-exist")
        self.assertEqual(ESignTransaction.objects.count(), 0)

    def test_non_pdf_source_is_refused(self):
        """Only PDFs can be signed."""
        docx = self.files.add(b"not a pdf", content_type="application/msword")
        with self.assertRaises(ESignNotAPDF):
            self.initiate_service(file_id=docx)
        self.assertEqual(ESignTransaction.objects.count(), 0)

    def test_invalid_placement_is_refused(self):
        """A placement the PDF Service rejects never becomes a transaction."""
        self.pdf.fail_prepare = ESignInvalidPlaceholder()
        with self.assertRaises(ESignInvalidPlaceholder):
            self.initiate_service()
        self.assertEqual(ESignTransaction.objects.count(), 0)

    def test_pdf_service_failure_stores_nothing(self):
        """A preparation failure is reported and nothing is persisted."""
        self.pdf.fail_prepare = ESignPDFError()
        with self.assertRaises(ESignPDFError) as caught:
            self.initiate_service()
        self.assertEqual(caught.exception.code, ESIGN_PDF_PREPARATION_FAILED)
        self.assertEqual(ESignTransaction.objects.count(), 0)

    def test_file_storage_failure_stores_nothing(self):
        """A placeholder upload failure is reported and nothing is persisted."""
        self.files.fail_upload = ESignFileStorageError()
        with self.assertRaises(ESignFileStorageError) as caught:
            self.initiate_service()
        self.assertEqual(caught.exception.code, ESIGN_FILE_STORAGE_UNAVAILABLE)
        self.assertEqual(ESignTransaction.objects.count(), 0)

    def test_provider_build_failure_leaves_a_failed_transaction(self):
        """Once the row exists, the failure is recorded on it."""
        with patch(
            "apps.esign.providers.mock.MockESignProvider.build_initiation",
            side_effect=RuntimeError("keystore gone"),
        ):
            with self.assertRaises(ESignRequestBuildFailed):
                self.initiate_service()

        transaction = ESignTransaction.objects.get()
        self.assertEqual(transaction.status, ESignStatus.FAILURE.value)
        self.assertEqual(transaction.failure_code, ESIGN_REQUEST_BUILD_FAILED)
        self.assertTrue(transaction.failure_message)
        # The placeholder is kept so a retry does not re-prepare the source.
        self.assertTrue(transaction.placeholder_file_id)
        # Nothing about the provider's internal error travels to the client.
        self.assertNotIn("keystore", transaction.failure_message)

    def test_permission_denial_stores_nothing(self):
        """Whether a user may sign is the owning module's decision."""
        permissions.register_entity_authorizer("ORDER", lambda **kwargs: False)
        self.addCleanup(permissions.unregister_entity_authorizer, "ORDER")

        with self.assertRaises(ESignNotPermitted):
            self.initiate_service()
        self.assertEqual(ESignTransaction.objects.count(), 0)
        self.assertEqual(self.files.uploads, [])

    def test_registered_authorizer_receives_the_entity_context(self):
        """The authorizer is called with the user and the entity it guards."""
        seen = {}

        def authorizer(**kwargs):
            seen.update(kwargs)
            return True

        permissions.register_entity_authorizer("ORDER", authorizer)
        self.addCleanup(permissions.unregister_entity_authorizer, "ORDER")

        self.initiate_service()

        self.assertEqual(seen["user"], self.user)
        self.assertEqual(seen["entity_type"], "ORDER")
        self.assertEqual(seen["entity_id"], "9f2c0001")

    def test_request_audit_is_persisted_without_secrets(self):
        """Only non-sensitive request metadata is stored."""
        with patch("apps.esign.providers.mock.MockESignProvider.build_initiation") as build:
            build.return_value = type(
                "Initiation",
                (),
                {
                    "esign_url": "https://esp.example/esign",
                    "form_fields": {"eSignRequest": "abc"},
                    "provider_transaction_id": "orders-audit",
                    "request_audit": {
                        "asp_id": "ASP-1",
                        "keystore_password": "hunter2",
                        "signature": "x" * 400,
                        "signature_count": 1,
                    },
                },
            )()
            result = self.initiate_service()

        audit = result.transaction.request_audit
        self.assertEqual(audit["asp_id"], "ASP-1")
        self.assertEqual(audit["signature_count"], 1)
        self.assertNotIn("keystore_password", audit)
        self.assertNotIn("signature", audit)


class DuplicateProviderIdTests(ESignTestCase):
    """A provider that re-issues an existing correlation id."""

    def test_duplicate_provider_transaction_id_fails_the_new_row(self):
        """The unique pair holds, and the new attempt is recorded as failed."""
        first = self.create_transaction(provider_transaction_id="orders-duplicate")

        with patch("apps.esign.providers.mock.MockESignProvider.build_initiation") as build:
            build.return_value = ESignInitiation(
                esign_url="https://esp.example/esign",
                form_fields={"eSignRequest": "abc"},
                provider_transaction_id=first.provider_transaction_id,
                request_audit={},
            )
            with self.assertRaises(ESignRequestBuildFailed):
                initiate_esign(
                    user=self.user,
                    module="orders",
                    file_id=self.source_file_id,
                    sign_placeholder=dict(PLACEHOLDER),
                )

        duplicate = ESignTransaction.objects.exclude(pk=first.pk).get()
        self.assertEqual(duplicate.status, ESignStatus.FAILURE.value)
        self.assertEqual(duplicate.failure_code, ESIGN_REQUEST_BUILD_FAILED)
        self.assertEqual(duplicate.provider_transaction_id, "")


class InProgressGuardTests(ESignTestCase):
    """A fresh initiation is refused while the document is already being signed.

    This is what stops a client bypassing the retry budget by calling ``_esign``
    repeatedly instead of ``_retry`` (spec 0015 #6.4).
    """

    def initiate_service(self, **overrides):
        """Call the service with the standard arguments."""

        kwargs = {
            "user": self.user,
            "module": "orders",
            "file_id": self.source_file_id,
            "entity_type": "ORDER",
            "entity_id": "9f2c0001",
            "organization_id": None,
            "sign_placeholder": dict(PLACEHOLDER),
        }
        kwargs.update(overrides)
        return initiate_esign(**kwargs)

    def test_second_initiation_while_pending_is_refused(self):
        """A live PENDING attempt blocks a new one, and nothing is stored."""
        self.initiate_service()
        uploads_before = len(self.files.uploads)

        with self.assertRaises(ESignAlreadyInProgress):
            self.initiate_service()

        self.assertEqual(ESignTransaction.objects.count(), 1)
        # No placeholder was prepared or stored for the refused call.
        self.assertEqual(len(self.files.uploads), uploads_before)

    def test_initiation_while_signing_is_refused(self):
        """An attempt mid-callback (SIGNING) also blocks a new one."""
        first = self.create_transaction()
        first.mark_signing()

        with self.assertRaises(ESignAlreadyInProgress):
            self.initiate_service()

    def test_a_new_attempt_is_allowed_once_the_previous_one_is_terminal(self):
        """Abandoning a signing (EXPIRED) or a failure frees the document."""
        for terminal in (
            ESignStatus.EXPIRED.value,
            ESignStatus.FAILURE.value,
            ESignStatus.SUCCESS.value,
        ):
            ESignTransaction.objects.all().delete()
            self.create_transaction(status=terminal, signed_file_id="signed-1")

            # A terminal transaction does not hold the document.
            result = self.initiate_service()
            self.assertEqual(result.transaction.status, ESignStatus.PENDING.value)

    def test_a_different_document_is_not_blocked(self):
        """The guard is scoped to one document, not the whole user."""
        self.create_transaction()
        other_file = self.files.add(SOURCE_PDF)

        result = self.initiate_service(file_id=other_file)
        self.assertEqual(result.transaction.source_file_id, other_file)

    def test_a_different_entity_on_the_same_file_is_not_blocked(self):
        """The same file signed for a different entity is a different document."""
        self.create_transaction()

        result = self.initiate_service(entity_type="JUDGEMENT", entity_id="different")
        self.assertEqual(result.transaction.entity_type, "JUDGEMENT")


class CachingExclusionTests(ESignTestCase):
    """Transaction rows must never be served from the ORM cache (spec 0012)."""

    def test_transaction_table_is_excluded_from_cachalot(self):
        """Status is read straight after it is written, under a lock."""
        from django.conf import settings

        self.assertIn(ESignTransaction._meta.db_table, settings.CACHALOT_UNCACHABLE_TABLES)
