"""Signing primitives (#14): prepare_for_signing / embed_signature via pyHanko.

A throw-away self-signed certificate stands in for the ESP: it signs the
digest returned by ``prepare_for_signing``, producing the detached PKCS#7 that
``embed_signature`` writes into the reserved container. The result is then
validated with pyHanko's own validator.
"""

import asyncio
import hashlib
import io
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from asn1crypto import keys as asn1_keys
from asn1crypto import x509 as asn1_x509
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.sign import fields, signers
from pyhanko.sign.validation import validate_pdf_signature
from pyhanko_certvalidator import ValidationContext
from pyhanko_certvalidator.registry import SimpleCertificateStore
from pypdf import PdfWriter

from apps.pdf.exceptions import (
    PDFEncrypted,
    PDFInvalidPKCS7,
    PDFInvalidPlaceholder,
    PDFNotParsable,
    PDFPageOutOfRange,
    PDFSignatureContainerTooSmall,
    PDFSignatureFieldMissing,
    PDFSigningError,
    PDFTooLarge,
)
from apps.pdf.services.signing import embed_signature, prepare_for_signing
from apps.pdf.tests.factories import simple_pdf

PLACEHOLDER = {
    "page": 1,
    "x": 380,
    "y": 60,
    "width": 160,
    "height": 60,
    "reason": "Approved",
    "location": "District Court, Ernakulam",
    "signer_name": "Presiding Officer",
}


@pytest.fixture(scope="module")
def esp():
    """A self-signed signer standing in for the ESP."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test ESP Signer")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(
            x509.KeyUsage(True, True, False, False, False, False, False, False, False),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    asn1_cert = asn1_x509.Certificate.load(cert.public_bytes(serialization.Encoding.DER))
    asn1_key = asn1_keys.PrivateKeyInfo.load(
        key.private_bytes(
            serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    signer = signers.SimpleSigner(
        signing_cert=asn1_cert,
        signing_key=asn1_key,
        cert_registry=SimpleCertificateStore.from_certs([asn1_cert]),
    )
    return signer, asn1_cert


def esp_sign(esp, document_hash: str) -> bytes:
    """Sign the hex digest the way the ESP would and return DER PKCS#7."""
    signer, _ = esp
    cms = asyncio.run(signer.async_sign(bytes.fromhex(document_hash), "sha256"))
    return cms.dump()


def signatures(pdf: bytes):
    return PdfFileReader(io.BytesIO(pdf)).embedded_signatures


def placeholder_field(pdf: bytes, index=0):
    """Return ``(field_name, field_dict, sig_dict)`` of a not-yet-signed field.

    ``embedded_signatures`` parses ``/Contents`` as CMS, which an empty
    reserved container is not, so prepared documents are inspected directly.
    """
    reader = PdfFileReader(io.BytesIO(pdf))
    name, value, ref = list(fields.enumerate_sig_fields(reader))[index]
    return name, ref.get_object(), value.get_object()


def assert_valid(pdf: bytes, esp, index=0):
    _, cert = esp
    status = validate_pdf_signature(signatures(pdf)[index], ValidationContext(trust_roots=[cert]))
    assert status.intact and status.valid, status.pretty_print_details()
    return status


class TestPrepare:
    def test_reserves_container_and_hashes_the_byte_range(self, settings):
        source = simple_pdf()
        prepared = prepare_for_signing(source, PLACEHOLDER)

        assert prepared.field_name == "Signature1"
        assert len(prepared.document_hash) == 64
        assert prepared.document_hash == prepared.document_hash.lower()
        # Incremental update: the original bytes are a strict prefix.
        assert prepared.prepared_document.startswith(source)

        _, _, sig = placeholder_field(prepared.prepared_document)
        byte_range = [int(v) for v in sig["/ByteRange"]]
        doc = prepared.prepared_document
        covered = doc[: byte_range[1]] + doc[byte_range[2] : byte_range[2] + byte_range[3]]
        assert hashlib.sha256(covered).hexdigest() == prepared.document_hash
        # The reserved region holds exactly the configured container size.
        assert (byte_range[2] - byte_range[1] - 2) // 2 == settings.PDF_SIGNATURE_CONTAINER_BYTES
        assert byte_range[2] + byte_range[3] == len(doc)

    def test_signature_dictionary_and_field(self):
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        name, field, sig = placeholder_field(prepared.prepared_document)
        assert name == "Signature1"
        assert sig["/Reason"] == "Approved"
        assert sig["/Location"] == "District Court, Ernakulam"
        assert sig["/SubFilter"] == "/adbe.pkcs7.detached"
        rect = [float(v) for v in field["/Rect"]]
        assert rect == [380, 60, 540, 120]

    def test_hash_is_stable_for_the_same_prepared_bytes_and_changes_with_the_document(self):
        first = prepare_for_signing(simple_pdf(text="A"), PLACEHOLDER)
        other = prepare_for_signing(simple_pdf(text="B"), PLACEHOLDER)

        _, _, sig = placeholder_field(first.prepared_document)
        byte_range = [int(v) for v in sig["/ByteRange"]]
        doc = first.prepared_document
        recomputed = hashlib.sha256(
            doc[: byte_range[1]] + doc[byte_range[2] : byte_range[2] + byte_range[3]]
        ).hexdigest()
        assert recomputed == first.document_hash
        assert other.document_hash != first.document_hash

    def test_negative_page_addresses_from_the_end(self):
        prepared = prepare_for_signing(simple_pdf(pages=3), {**PLACEHOLDER, "page": -1})
        _, field, _ = placeholder_field(prepared.prepared_document)
        reader = PdfFileReader(io.BytesIO(prepared.prepared_document))
        kids = reader.root["/Pages"]["/Kids"]
        annots = [kids[i].get_object().get("/Annots") or [] for i in range(3)]
        assert [len(a) for a in annots] == [0, 0, 1]
        assert annots[2][0].get_object()["/T"] == "Signature1"

    def test_non_latin_signer_names_are_drawn(self):
        prepared = prepare_for_signing(
            simple_pdf(), {**PLACEHOLDER, "signer_name": "ജഡ്ജി", "reason": "", "location": ""}
        )
        assert prepared.document_hash

    def test_hash_algorithm_follows_settings(self, settings):
        settings.PDF_SIGNATURE_HASH_ALGORITHM = "SHA512"
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        assert len(prepared.document_hash) == 128

    @pytest.mark.django_db
    def test_no_job_rows_and_no_file_storage_calls(self, django_assert_num_queries):
        with (
            patch("apps.files.services.upload_file") as upload,
            patch("apps.files.services.get_file_content") as content,
            django_assert_num_queries(0),
        ):
            prepare_for_signing(simple_pdf(), PLACEHOLDER)
        upload.assert_not_called()
        content.assert_not_called()


class TestEmbed:
    def test_signed_pdf_verifies_over_the_whole_document(self, esp):
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        signed = embed_signature(
            prepared.prepared_document, esp_sign(esp, prepared.document_hash), prepared.field_name
        )

        assert len(signed) == len(prepared.prepared_document)
        status = assert_valid(signed, esp)
        assert status.coverage.name == "ENTIRE_FILE"

    def test_only_the_reserved_region_changes_and_output_is_deterministic(self, esp):
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        pkcs7 = esp_sign(esp, prepared.document_hash)
        signed = embed_signature(prepared.prepared_document, pkcs7, prepared.field_name)

        _, _, sig = placeholder_field(prepared.prepared_document)
        byte_range = [int(v) for v in sig["/ByteRange"]]
        start, end = byte_range[1], byte_range[2]
        assert signed[:start] == prepared.prepared_document[:start]
        assert signed[end:] == prepared.prepared_document[end:]
        assert embed_signature(prepared.prepared_document, pkcs7, prepared.field_name) == signed

    def test_already_signed_document_keeps_earlier_signature_valid(self, esp):
        first = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        once = embed_signature(
            first.prepared_document, esp_sign(esp, first.document_hash), first.field_name
        )

        second = prepare_for_signing(once, {**PLACEHOLDER, "y": 140})
        assert second.field_name == "Signature2"
        assert second.prepared_document.startswith(once)
        twice = embed_signature(
            second.prepared_document, esp_sign(esp, second.document_hash), second.field_name
        )

        assert len(signatures(twice)) == 2
        assert_valid(twice, esp, index=0)
        assert_valid(twice, esp, index=1)

    def test_container_too_small_is_rejected_not_re_prepared(self, esp, settings):
        settings.PDF_SIGNATURE_CONTAINER_BYTES = 512
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        with pytest.raises(PDFSignatureContainerTooSmall):
            embed_signature(
                prepared.prepared_document,
                esp_sign(esp, prepared.document_hash),
                prepared.field_name,
            )
        # The prepared document is untouched: nothing was re-prepared.
        _, _, sig = placeholder_field(prepared.prepared_document)
        assert not any(sig["/Contents"])

    def test_source_at_the_size_limit_can_still_be_embedded(self, esp, settings):
        source = simple_pdf()
        settings.PDF_MAX_SIGN_INPUT_BYTES = len(source)
        prepared = prepare_for_signing(source, PLACEHOLDER)
        assert len(prepared.prepared_document) > len(source)

        signed = embed_signature(
            prepared.prepared_document, esp_sign(esp, prepared.document_hash), prepared.field_name
        )
        assert_valid(signed, esp)

    def test_unknown_field_is_missing(self, esp):
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        with pytest.raises(PDFSignatureFieldMissing):
            embed_signature(
                prepared.prepared_document, esp_sign(esp, prepared.document_hash), "Other"
            )

    def test_filled_container_cannot_be_filled_again(self, esp):
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        pkcs7 = esp_sign(esp, prepared.document_hash)
        signed = embed_signature(prepared.prepared_document, pkcs7, prepared.field_name)
        with pytest.raises(PDFSignatureFieldMissing):
            embed_signature(signed, pkcs7, prepared.field_name)

    def test_document_modified_after_preparation_is_rejected(self, esp):
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        tampered = prepared.prepared_document + b"\n% appended\n"
        with pytest.raises(PDFSignatureFieldMissing):
            embed_signature(tampered, esp_sign(esp, prepared.document_hash), prepared.field_name)

    @pytest.mark.parametrize("pkcs7", [b"", b"not der", b"\x30\x03\x02\x01\x01"])
    def test_invalid_pkcs7_is_rejected(self, pkcs7):
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        with pytest.raises(PDFInvalidPKCS7):
            embed_signature(prepared.prepared_document, pkcs7, prepared.field_name)


class TestErrors:
    def test_errors_share_a_base_class(self):
        for error in (
            PDFNotParsable,
            PDFEncrypted,
            PDFPageOutOfRange,
            PDFInvalidPlaceholder,
            PDFSignatureFieldMissing,
            PDFSignatureContainerTooSmall,
        ):
            assert issubclass(error, PDFSigningError)

    @pytest.mark.parametrize("document", [b"", b"hello world", b"%PDF-1.7\ngarbage"])
    def test_non_pdf_input(self, document):
        with pytest.raises(PDFNotParsable):
            prepare_for_signing(document, PLACEHOLDER)

    def test_encrypted_pdf(self):
        writer = PdfWriter(clone_from=io.BytesIO(simple_pdf()))
        writer.encrypt(user_password="secret", algorithm="AES-128")
        out = io.BytesIO()
        writer.write(out)
        with pytest.raises(PDFEncrypted):
            prepare_for_signing(out.getvalue(), PLACEHOLDER)

    def test_oversized_input(self, settings):
        settings.PDF_MAX_SIGN_INPUT_BYTES = 100
        with pytest.raises(PDFTooLarge):
            prepare_for_signing(simple_pdf(), PLACEHOLDER)

    @pytest.mark.parametrize("page", [2, -2, 99])
    def test_page_out_of_range(self, page):
        with pytest.raises(PDFPageOutOfRange):
            prepare_for_signing(simple_pdf(), {**PLACEHOLDER, "page": page})

    @pytest.mark.parametrize(
        "placeholder",
        [
            "not a dict",
            {**PLACEHOLDER, "colour": "red"},
            {key: value for key, value in PLACEHOLDER.items() if key != "width"},
            {**PLACEHOLDER, "page": 0},
            {**PLACEHOLDER, "page": True},
            {**PLACEHOLDER, "x": -1},
            {**PLACEHOLDER, "width": 0},
            {**PLACEHOLDER, "height": "60"},
            {**PLACEHOLDER, "x": 500},
            {**PLACEHOLDER, "y": 800},
            {**PLACEHOLDER, "reason": 5},
            {**PLACEHOLDER, "signer_name": "x" * 201},
        ],
    )
    def test_invalid_placeholder(self, placeholder):
        with pytest.raises(PDFInvalidPlaceholder):
            prepare_for_signing(simple_pdf(), placeholder)

    def test_messages_never_include_document_content(self):
        secret = b"%PDF-1.4\nTOP-SECRET-CONTENT"
        with pytest.raises(PDFNotParsable) as excinfo:
            prepare_for_signing(secret, PLACEHOLDER)
        assert "TOP-SECRET" not in str(excinfo.value)


def test_logs_never_contain_hashes_or_bytes(caplog, esp):
    with caplog.at_level("INFO", logger="apps.pdf"):
        prepared = prepare_for_signing(simple_pdf(), PLACEHOLDER)
        embed_signature(
            prepared.prepared_document, esp_sign(esp, prepared.document_hash), prepared.field_name
        )
    log_text = caplog.text
    assert "operation=prepare" in log_text and "operation=embed" in log_text
    assert prepared.document_hash not in log_text
