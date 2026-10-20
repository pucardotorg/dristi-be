"""Merge and split PDF documents (spec 0016 #8, #11)."""

from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from ..exceptions import PDFRenderError


def _reader(document: bytes) -> PdfReader:
    try:
        return PdfReader(io.BytesIO(document))
    except (PdfReadError, ValueError, OSError) as exc:
        raise PDFRenderError("A document to merge or split is not a valid PDF.") from exc


def merge(documents: list[bytes]) -> bytes:
    """Concatenate ``documents`` in order into a single PDF."""
    if not documents:
        raise PDFRenderError("Nothing to merge.")
    if len(documents) == 1:
        return documents[0]
    writer = PdfWriter()
    for document in documents:
        writer.append(_reader(document))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def page_count(document: bytes) -> int:
    """Return the number of pages in ``document``."""
    return len(_reader(document).pages)


def split(document: bytes, pages_per_part: int) -> list[bytes]:
    """Split ``document`` into parts of at most ``pages_per_part`` pages."""
    if pages_per_part < 1:
        raise PDFRenderError("pages_per_part must be at least 1.")
    reader = _reader(document)
    total = len(reader.pages)
    parts = []
    for start in range(0, total, pages_per_part):
        writer = PdfWriter()
        for index in range(start, min(start + pages_per_part, total)):
            writer.add_page(reader.pages[index])
        out = io.BytesIO()
        writer.write(out)
        parts.append(out.getvalue())
    return parts
