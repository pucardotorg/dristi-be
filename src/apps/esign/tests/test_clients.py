"""Adapter tests for the PDF and File Storage clients (spec 0015 #4)."""

import io
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.esign.clients.files import FileClient
from apps.esign.clients.pdf import PDFClient
from apps.esign.exceptions import (
    ESignFileStorageError,
    ESignInvalidPlaceholder,
    ESignPDFEmbedError,
    ESignPDFError,
    ESignSourceNotFound,
)

from .base import PLACEHOLDER


class PDFPageOutOfRange(Exception):  # noqa: N818
    """Stands in for the 0016 #14.3 exception of the same name."""


class PDFNotParsable(Exception):  # noqa: N818
    """Stands in for the 0016 #14.3 exception of the same name."""


def signing_module(**overrides):
    """Return a stub ``apps.pdf.services.signing`` module."""

    module = SimpleNamespace(
        prepare_for_signing=lambda document, placeholder: SimpleNamespace(
            prepared_document=document + b"-prepared",
            document_hash="ABC123",
            field_name="Signature1",
        ),
        embed_signature=lambda prepared, pkcs7, field_name: prepared + pkcs7,
    )
    for name, value in overrides.items():
        setattr(module, name, value)
    return module


def raising(exception):
    """Return a callable that raises ``exception``."""

    def call(*args, **kwargs):
        raise exception

    return call


class PDFClientTests(SimpleTestCase):
    """The narrow adapter over ``apps.pdf.services.signing``."""

    def setUp(self):
        """Work against a stub signing module."""
        self.client = PDFClient()

    def use(self, module):
        """Point the adapter at ``module`` for the duration of the test."""
        patcher = patch.object(PDFClient, "_signing_module", return_value=module)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_the_documented_placement_keys_are_forwarded(self):
        """0016 rejects unknown keys, so the adapter drops the extras."""
        self.assertEqual(
            PDFClient.to_pdf_placeholder(PLACEHOLDER),
            {
                "page": 1,
                "x": 380,
                "y": 60,
                "width": 160,
                "height": 60,
                "reason": "Approved",
                "location": "District Court, Ernakulam",
            },
        )

    def test_prepared_result_is_normalised(self):
        """The hash is lowercased and the result carries all three values."""
        self.use(signing_module())
        prepared = self.client.prepare_for_signing(b"%PDF", dict(PLACEHOLDER))

        self.assertEqual(prepared.prepared_document, b"%PDF-prepared")
        self.assertEqual(prepared.document_hash, "abc123")
        self.assertEqual(prepared.field_name, "Signature1")

    def test_incomplete_result_is_an_error(self):
        """A result missing the hash cannot be signed against."""
        self.use(
            signing_module(
                prepare_for_signing=lambda document, placeholder: SimpleNamespace(
                    prepared_document=b"x", document_hash="", field_name="f"
                )
            )
        )
        with self.assertRaises(ESignPDFError):
            self.client.prepare_for_signing(b"%PDF", dict(PLACEHOLDER))

    def test_placement_errors_map_to_invalid_placeholder(self):
        """A page or placement problem is the caller's, not the service's."""
        self.use(signing_module(prepare_for_signing=raising(PDFPageOutOfRange("page 9"))))
        with self.assertRaises(ESignInvalidPlaceholder):
            self.client.prepare_for_signing(b"%PDF", dict(PLACEHOLDER))

    def test_other_pdf_errors_map_to_preparation_failed(self):
        """Every other PDF failure is reported generically."""
        self.use(signing_module(prepare_for_signing=raising(PDFNotParsable("/tmp/x.pdf"))))
        with self.assertRaises(ESignPDFError) as caught:
            self.client.prepare_for_signing(b"%PDF", dict(PLACEHOLDER))
        # The service's message may name internals, so it must not travel.
        self.assertNotIn("/tmp/x.pdf", caught.exception.message)

    def test_embed_failures_map_to_embed_failed(self):
        """Embedding is a distinct failure code from preparation."""
        self.use(signing_module(embed_signature=raising(RuntimeError("boom"))))
        with self.assertRaises(ESignPDFEmbedError):
            self.client.embed_signature(b"%PDF", b"pkcs7", "Signature1")

    def test_embedded_document_is_returned(self):
        """The signed bytes come straight back from the service."""
        self.use(signing_module())
        self.assertEqual(self.client.embed_signature(b"%PDF", b"pkcs7", "Signature1"), b"%PDFpkcs7")

    @override_settings(PDF_MAX_SIGN_INPUT_BYTES=4)
    def test_oversized_documents_are_refused(self):
        """The adapter enforces the configured input limit."""
        self.use(signing_module())
        with self.assertRaises(ESignPDFError):
            self.client.prepare_for_signing(b"%PDF-1.7", dict(PLACEHOLDER))

    def test_missing_pdf_module_is_reported_safely(self):
        """A deployment without the PDF Service fails with a safe message."""
        with self.assertRaises(ESignPDFError):
            self.client.prepare_for_signing(b"%PDF", dict(PLACEHOLDER))


class FileClientTests(SimpleTestCase):
    """The narrow adapter over ``apps.files.services``."""

    def setUp(self):
        """Work against a stub file service module."""
        self.client = FileClient()
        self.uploaded = {}

    def use(self, module):
        """Point the adapter at ``module`` for the duration of the test."""
        patcher = patch.object(FileClient, "_service_module", return_value=module)
        patcher.start()
        self.addCleanup(patcher.stop)

    def service_module(self, **overrides):
        """Return a stub module implementing the 0014 service functions."""

        def upload_file(payload):
            self.uploaded = payload
            return {"files": [{"id": "new-file"}]}

        module = SimpleNamespace(
            get_file=lambda file_id: {"id": file_id, "content_type": "application/pdf"},
            get_file_content=lambda file_id: io.BytesIO(b"%PDF"),
            upload_file=upload_file,
            delete_file=lambda file_id: None,
        )
        for name, value in overrides.items():
            setattr(module, name, value)
        return module

    def test_metadata_is_returned_as_a_dict(self):
        """Metadata reads pass straight through."""
        self.use(self.service_module())
        self.assertEqual(
            self.client.get_metadata("f1"),
            {"id": "f1", "content_type": "application/pdf"},
        )

    def test_model_instances_are_accepted(self):
        """A ``File`` instance is normalised to the documented dict shape."""
        instance = SimpleNamespace(id="f1", content_type="application/pdf", file_name="a.pdf")
        self.use(self.service_module(get_file=lambda file_id: instance))
        self.assertEqual(self.client.get_metadata("f1")["content_type"], "application/pdf")

    def test_content_is_read_and_the_stream_closed(self):
        """The caller owns closing the stream, so the adapter does it."""
        stream = io.BytesIO(b"%PDF")
        self.use(self.service_module(get_file_content=lambda file_id: stream))

        self.assertEqual(self.client.get_content("f1"), b"%PDF")
        self.assertTrue(stream.closed)

    @override_settings(PDF_MAX_SIGN_INPUT_BYTES=2)
    def test_content_above_the_read_limit_is_refused(self):
        """The configured read limit guards against loading a huge file."""
        self.use(self.service_module())
        with self.assertRaises(ESignFileStorageError):
            self.client.get_content("f1")

    def test_unknown_file_is_reported_as_not_found(self):
        """The storage module's not-found error is mapped, not leaked."""

        class DoesNotExist(Exception):  # noqa: N818
            """Mimics ``File.DoesNotExist``."""

        self.use(self.service_module(get_file=raising(DoesNotExist())))
        with self.assertRaises(ESignSourceNotFound):
            self.client.get_metadata("missing")

    def test_upload_uses_the_single_file_batch_shape(self):
        """The domain never sees the batch envelope."""
        self.use(self.service_module())

        file_id = self.client.upload(
            b"%PDF",
            filename="a-prepared.pdf",
            file_type="PDF",
            user_id="user-1",
            organization_id=None,
            tags=["esign", "orders"],
        )

        self.assertEqual(file_id, "new-file")
        self.assertEqual(self.uploaded["user_id"], "user-1")
        self.assertIsNone(self.uploaded["organization_id"])
        entry = self.uploaded["files"][0]
        self.assertEqual(entry["file_type"], "PDF")
        self.assertEqual(entry["tags"], ["esign", "orders"])
        self.assertEqual(entry["file"].content_type, "application/pdf")

    def test_upload_without_a_file_id_is_an_error(self):
        """A storage response with no id cannot be persisted against."""
        self.use(self.service_module(upload_file=lambda payload: {"files": []}))
        with self.assertRaises(ESignFileStorageError):
            self.client.upload(b"%PDF", filename="a.pdf", file_type="PDF", user_id="user-1")

    def test_delete_is_delegated(self):
        """Cleanup calls the storage module's delete."""
        deleted = []
        self.use(self.service_module(delete_file=deleted.append))
        self.client.delete("f1")
        self.assertEqual(deleted, ["f1"])

    def test_missing_file_module_is_reported_safely(self):
        """A deployment without the storage module fails with a safe message."""
        with self.assertRaises(ESignFileStorageError):
            self.client.get_metadata("f1")
