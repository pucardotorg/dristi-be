"""PDF signature primitives consumed by eSign (spec 0016 #14), built on pyHanko.

Two synchronous, bytes-in/bytes-out functions::

    prepare_for_signing(document, placeholder) -> PreparedDocument
    embed_signature(prepared_document, pkcs7, field_name) -> bytes

``prepare_for_signing`` appends an incremental update to the input that adds a
visible signature field and a signature dictionary whose ``/Contents`` is an
empty (zero-filled) container of ``PDF_SIGNATURE_CONTAINER_BYTES`` bytes, and
returns the digest over the resulting ``/ByteRange``. That digest is what the
ESP signs. ``embed_signature`` writes the detached PKCS#7 returned by the ESP
into that container and changes no other byte, so the digest -- and every
earlier signature -- stays valid.

Boundaries: no ``PDFJob`` row, no ``apps.files`` call, no key material, no
REST surface. The caller stores the prepared bytes verbatim between the two
calls, because the digest is only valid for exactly those bytes. Logs record
the operation, page, container size and outcome only -- never document bytes,
digests or PKCS#7 content.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import io
import logging
from dataclasses import dataclass
from functools import lru_cache

from asn1crypto import cms
from django.conf import settings
from pyhanko.pdf_utils.font.opentype import GlyphAccumulatorFactory
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.reader import PdfFileReader
from pyhanko.pdf_utils.rw_common import find_inherited_value_in_tree
from pyhanko.pdf_utils.text import TextBoxStyle
from pyhanko.sign import fields, signers
from pyhanko.sign.fields import SigSeedSubFilter
from pyhanko.sign.signers.pdf_byterange import PreparedByteRangeDigest
from pyhanko.stamp import TextStampStyle

from ..exceptions import (
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
from ..renderer import fonts

logger = logging.getLogger("apps.pdf")

SUPPORTED_HASH_ALGORITHMS = {"SHA256": "sha256", "SHA384": "sha384", "SHA512": "sha512"}

PLACEHOLDER_KEYS = {"page", "x", "y", "width", "height", "reason", "location", "signer_name"}
PLACEHOLDER_REQUIRED = {"page", "x", "y", "width", "height"}
PLACEHOLDER_TEXT_KEYS = ("signer_name", "reason", "location")
MAX_TEXT_LENGTH = 200
FIELD_PREFIX = "Signature"
DEFAULT_APPEARANCE_TEXT = "Digitally signed"
# Allowance for the incremental update besides the container itself; matches
# PREPARED_DOCUMENT_OVERHEAD_BYTES in the eSign PDF adapter (spec 0015 #4.1).
PREPARED_OVERHEAD_BYTES = 65536


@dataclass(frozen=True)
class PreparedDocument:
    """Result of ``prepare_for_signing``."""

    prepared_document: bytes
    document_hash: str
    field_name: str

    def __repr__(self):
        return (
            f"PreparedDocument(field_name={self.field_name!r}, size={len(self.prepared_document)})"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def prepare_for_signing(document: bytes, placeholder: dict) -> PreparedDocument:
    """Reserve an empty signature container and return the ByteRange digest (#14.1)."""
    reader = _open(document)
    spec = _validated_placeholder(placeholder)
    page_index = _page_index(reader, spec["page"])
    box = _field_box(reader, page_index, spec)
    field_name = _new_field_name(reader)
    md_algorithm = hash_algorithm()
    container_bytes = settings.PDF_SIGNATURE_CONTAINER_BYTES

    font_path, text = _appearance_font(appearance_text(spec))
    writer = IncrementalPdfFileWriter(io.BytesIO(document), strict=False)
    pdf_signer = signers.PdfSigner(
        signers.PdfSignatureMetadata(
            field_name=field_name,
            md_algorithm=md_algorithm,
            subfilter=SigSeedSubFilter.ADOBE_PKCS7_DETACHED,
            reason=spec.get("reason") or None,
            location=spec.get("location") or None,
            name=spec.get("signer_name") or None,
        ),
        # A placeholder signer: no key, no certificate. Only the digest step
        # runs here; the real signature comes back from the ESP.
        signer=signers.ExternalSigner(signing_cert=None, cert_registry=None),
        stamp_style=_stamp_style(font_path, text, spec["height"]),
        new_field_spec=fields.SigFieldSpec(field_name, on_page=page_index, box=box),
    )
    try:
        prepared, _, output = _run(
            pdf_signer.async_digest_doc_for_signing(
                writer,
                # pyHanko counts the reserved region in hex digits.
                bytes_reserved=container_bytes * 2,
                appearance_text_params={"sigtext": text},
                output=io.BytesIO(),
            )
        )
    except PDFSigningError:
        raise
    except Exception as exc:
        _log("prepare", page=spec["page"], container=container_bytes, outcome="error")
        raise PDFSigningError("The PDF could not be prepared for signing.") from exc

    _log("prepare", page=spec["page"], container=container_bytes, outcome="ok")
    return PreparedDocument(
        prepared_document=output.getvalue(),
        document_hash=prepared.document_digest.hex(),
        field_name=field_name,
    )


def embed_signature(prepared_document: bytes, pkcs7: bytes, field_name: str) -> bytes:
    """Write ``pkcs7`` into the reserved container of ``field_name`` (#14.2).

    Pure and deterministic: only the reserved region changes, so the same
    inputs always produce the same output.
    """
    reader = _open(prepared_document, max_bytes=prepared_document_max_bytes())
    start, end = _reserved_region(reader, prepared_document, field_name)
    der = _validated_pkcs7(pkcs7)

    capacity = (end - start - 2) // 2
    if len(der) > capacity:
        _log("embed", container=capacity, outcome="too_small")
        raise PDFSignatureContainerTooSmall(
            f"The signature needs {len(der)} bytes but the container holds {capacity}."
        )

    output = io.BytesIO(prepared_document)
    PreparedByteRangeDigest(
        document_digest=b"", reserved_region_start=start, reserved_region_end=end
    ).fill_with_cms(output, der)
    _log("embed", container=capacity, outcome="ok")
    return output.getvalue()


def hash_algorithm() -> str:
    """Return the pyHanko digest name for ``PDF_SIGNATURE_HASH_ALGORITHM``."""
    configured = str(settings.PDF_SIGNATURE_HASH_ALGORITHM).upper().replace("-", "")
    try:
        return SUPPORTED_HASH_ALGORITHMS[configured]
    except KeyError as exc:
        raise PDFSigningError("PDF_SIGNATURE_HASH_ALGORITHM is not supported.") from exc


def appearance_text(spec: dict) -> str:
    """Return the text drawn in the signature field."""
    lines = []
    if spec.get("signer_name"):
        lines.append(f"Digitally signed by {spec['signer_name']}")
    if spec.get("reason"):
        lines.append(f"Reason: {spec['reason']}")
    if spec.get("location"):
        lines.append(f"Location: {spec['location']}")
    return "\n".join(lines) or DEFAULT_APPEARANCE_TEXT


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def prepared_document_max_bytes() -> int:
    """Size limit for a prepared document passed to ``embed_signature``.

    Preparation appends the reserved container -- written hex-encoded, two
    characters per byte -- plus the signature dictionary, widget, appearance
    stream and cross-reference section. Checking the prepared document against
    the source limit would reject, at embed time, a source that was accepted
    at preparation, after the signer has already completed the ESP flow.
    """
    return (
        settings.PDF_MAX_SIGN_INPUT_BYTES
        + 2 * settings.PDF_SIGNATURE_CONTAINER_BYTES
        + PREPARED_OVERHEAD_BYTES
    )


def _open(document: bytes, max_bytes: int | None = None) -> PdfFileReader:
    """Parse ``document``, enforcing size and encryption rules."""
    if not isinstance(document, bytes | bytearray):
        raise PDFNotParsable()
    limit = settings.PDF_MAX_SIGN_INPUT_BYTES if max_bytes is None else max_bytes
    if len(document) > limit:
        raise PDFTooLarge()
    if not bytes(document[:1024]).lstrip().startswith(b"%PDF-"):
        raise PDFNotParsable()
    try:
        reader = PdfFileReader(io.BytesIO(bytes(document)), strict=False)
        encrypted = reader.encrypted
        page_count = int(reader.root["/Pages"]["/Count"])
    except Exception as exc:
        raise PDFNotParsable() from exc
    if encrypted:
        raise PDFEncrypted()
    if page_count < 1:
        raise PDFNotParsable("The PDF has no pages.")
    return reader


def _number(value, key: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PDFInvalidPlaceholder(f"{key} must be a number.")
    if value < 0 or (positive and value <= 0):
        raise PDFInvalidPlaceholder(f"{key} must be {'positive' if positive else 'non-negative'}.")
    return float(value)


def _validated_placeholder(placeholder) -> dict:
    if not isinstance(placeholder, dict):
        raise PDFInvalidPlaceholder("The placeholder must be an object.")
    unknown = set(placeholder) - PLACEHOLDER_KEYS
    if unknown:
        raise PDFInvalidPlaceholder(f"Unknown placeholder keys: {', '.join(sorted(unknown))}.")
    missing = PLACEHOLDER_REQUIRED - set(placeholder)
    if missing:
        raise PDFInvalidPlaceholder(f"Missing placeholder keys: {', '.join(sorted(missing))}.")

    page = placeholder["page"]
    if isinstance(page, bool) or not isinstance(page, int) or page == 0:
        raise PDFInvalidPlaceholder("page must be a non-zero integer (1-based, -1 = last).")

    spec = {
        "page": page,
        "x": _number(placeholder["x"], "x"),
        "y": _number(placeholder["y"], "y"),
        "width": _number(placeholder["width"], "width", positive=True),
        "height": _number(placeholder["height"], "height", positive=True),
    }
    for key in PLACEHOLDER_TEXT_KEYS:
        value = placeholder.get(key, "")
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise PDFInvalidPlaceholder(f"{key} must be a string.")
        if len(value) > MAX_TEXT_LENGTH:
            raise PDFInvalidPlaceholder(f"{key} exceeds {MAX_TEXT_LENGTH} characters.")
        spec[key] = " ".join(value.split())
    return spec


def _page_index(reader: PdfFileReader, page: int) -> int:
    count = int(reader.root["/Pages"]["/Count"])
    index = page - 1 if page > 0 else count + page
    if not 0 <= index < count:
        raise PDFPageOutOfRange(f"Page {page} does not exist; the PDF has {count} page(s).")
    return index


def _field_box(reader: PdfFileReader, page_index: int, spec: dict) -> tuple:
    """Translate page-relative coordinates to the page's user space, checking bounds."""
    try:
        page_ref, _ = reader.find_page_for_modification(page_index)
        media_box = find_inherited_value_in_tree(page_ref.get_object(), "/MediaBox", "/Parent")
        llx, lly, urx, ury = (float(value) for value in media_box)
    except Exception as exc:
        raise PDFNotParsable("The page has no usable page box.") from exc

    left, bottom = min(llx, urx), min(lly, ury)
    page_width, page_height = abs(urx - llx), abs(ury - lly)
    if spec["x"] + spec["width"] > page_width or spec["y"] + spec["height"] > page_height:
        raise PDFInvalidPlaceholder("The signature box does not fit inside the page.")
    x1, y1 = left + spec["x"], bottom + spec["y"]
    return (x1, y1, x1 + spec["width"], y1 + spec["height"])


def _new_field_name(reader: PdfFileReader) -> str:
    existing = {name for name, _, _ in fields.enumerate_sig_fields(reader)}
    number = len(existing) + 1
    while f"{FIELD_PREFIX}{number}" in existing:
        number += 1
    return f"{FIELD_PREFIX}{number}"


def _reserved_region(reader: PdfFileReader, document: bytes, field_name: str) -> tuple[int, int]:
    """Return the ``(start, end)`` offsets of ``field_name``'s empty container.

    The container must be the field's only signature, still zero-filled, and
    its ``/ByteRange`` must reach the end of the file -- that is, nothing was
    appended after the document was prepared.
    """
    if not isinstance(field_name, str) or not field_name:
        raise PDFSignatureFieldMissing()
    try:
        matches = list(fields.enumerate_sig_fields(reader, with_name=field_name))
    except Exception as exc:
        raise PDFNotParsable() from exc
    if len(matches) != 1 or matches[0][1] is None:
        raise PDFSignatureFieldMissing()

    try:
        sig = matches[0][1].get_object()
        byte_range = [int(value) for value in sig["/ByteRange"]]
        contents = sig["/Contents"]
    except Exception as exc:
        raise PDFSignatureFieldMissing() from exc

    if len(byte_range) != 4 or byte_range[0] != 0:
        raise PDFSignatureFieldMissing()
    start, end = byte_range[1], byte_range[2]
    if any(contents):
        raise PDFSignatureFieldMissing("The signature container is already filled.")
    if byte_range[2] + byte_range[3] != len(document):
        raise PDFSignatureFieldMissing("The prepared PDF was modified after preparation.")
    region = document[start:end]
    if len(region) < 2 or region[:1] != b"<" or region[-1:] != b">" or region[1:-1].strip(b"0"):
        raise PDFSignatureFieldMissing("The signature container is not empty.")
    return start, end


def _validated_pkcs7(pkcs7) -> bytes:
    if not isinstance(pkcs7, bytes | bytearray) or not pkcs7:
        raise PDFInvalidPKCS7()
    der = bytes(pkcs7)
    try:
        content_info = cms.ContentInfo.load(der, strict=True)
        if content_info["content_type"].native != "signed_data":
            raise PDFInvalidPKCS7("The PKCS#7 structure is not SignedData.")
        content_info["content"].native  # noqa: B018 -- forces a full parse
    except PDFInvalidPKCS7:
        raise
    except Exception as exc:
        raise PDFInvalidPKCS7() from exc
    return der


# ---------------------------------------------------------------------------
# Appearance
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _font_cmap(path: str) -> frozenset[int]:
    from fontTools.ttLib import TTFont

    with TTFont(path, lazy=True) as font:
        return frozenset(font.getBestCmap())


def _appearance_font(text: str) -> tuple[str, str]:
    """Pick the bundled font that covers ``text`` and drop what it cannot draw.

    Indic text uses that script's family; characters the chosen font lacks are
    replaced with ``?`` so an unusual character cannot break preparation.
    """
    family = next(
        (fonts.font_for_char(char) for char in text if fonts.font_for_char(char)),
        fonts.DEFAULT_FONT,
    )
    path = str(fonts.FONT_DIR / fonts.PDF_FONTS[family]["regular"])
    cmap = _font_cmap(path)
    safe = "".join(char if char == "\n" or ord(char) in cmap else "?" for char in text)
    return path, safe


def _stamp_style(path: str, text: str, height: float) -> TextStampStyle:
    lines = text.count("\n") + 1
    size = max(5, min(10, int(height / (lines * 1.4))))
    return TextStampStyle(
        stamp_text="%(sigtext)s",
        border_width=1,
        text_box_style=TextBoxStyle(font=GlyphAccumulatorFactory(path, font_size=size)),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coroutine):
    """Run a pyHanko coroutine from synchronous code, even inside an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coroutine).result()


def _log(operation: str, **fields_) -> None:
    logger.info(
        "event=PDF_SIGNING operation=%s %s",
        operation,
        " ".join(f"{name}={value}" for name, value in fields_.items()),
    )
