"""Narrow adapters over the PDF and File Storage modules (spec 0015 #4).

Both modules are separate apps of this project, consumed in-process through
their published service functions. Resolving the adapters through these two
functions keeps the domain indifferent to their internals — and lets tests
substitute fakes without touching the services.
"""

from .files import FileClient
from .pdf import PDFClient, PreparedDocument

_pdf_client = PDFClient()
_file_client = FileClient()


def get_pdf_client() -> PDFClient:
    """Return the PDF Service adapter."""

    return _pdf_client


def get_file_client() -> FileClient:
    """Return the File Storage Service adapter."""

    return _file_client


__all__ = [
    "FileClient",
    "PDFClient",
    "PreparedDocument",
    "get_file_client",
    "get_pdf_client",
]
