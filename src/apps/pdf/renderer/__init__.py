"""PDF rendering (spec 0016 #8).

The renderer turns a *resolved* document description into PDF bytes. It never
talks to the database, ``apps.files`` or external services: images and QR
codes reach it as already-fetched ``ImageData`` values inside the context.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageData:
    """Normalized image bytes ready to be drawn.

    ``content`` is always PNG; ``width``/``height`` are its pixel dimensions,
    used to preserve the aspect ratio when only one drawn dimension is given.
    """

    content: bytes
    width: int
    height: int

    def __repr__(self):
        return f"ImageData({self.width}x{self.height}, {len(self.content)} bytes)"


class PDFRenderer:
    """Interface every renderer implements."""

    def render(self, document: dict, context: dict) -> bytes:
        """Render ``document`` (a ``format_config``) with ``context`` to PDF bytes."""
        raise NotImplementedError


def get_renderer() -> PDFRenderer:
    """Return the default pure-Python renderer."""
    from .python_renderer import PythonRenderer

    return PythonRenderer()


__all__ = ["ImageData", "PDFRenderer", "get_renderer"]
