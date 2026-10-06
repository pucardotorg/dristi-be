"""Image mapping (spec 0016 #5, ``ImageMapper``).

Fetches an image and normalizes it to PNG so the renderer only ever sees
validated, bounded image bytes. Mapping shape::

    {"type": "image", "target": "court_seal",
     "source": "data.seal_url",          # expression producing the reference
     "source_type": "url",               # url | base64 | file
     "max_width": 600, "max_height": 600,
     "on_error": "fail"}                 # fail | placeholder

``url`` references are fetched with ``PDF_IMAGE_DOWNLOAD_TIMEOUT_SECONDS``
and capped at ``PDF_IMAGE_MAX_BYTES``; ``base64`` accepts raw base64 or a
``data:`` URI; ``file`` reads an ``apps.files`` id through its service
function. When fetching keeps failing after the in-call retries,
``on_error: placeholder`` yields ``None`` -- rendered as an empty box --
instead of failing the document (#10).
"""

from __future__ import annotations

import base64
import binascii
import io
import logging

from django.conf import settings
from PIL import Image, UnidentifiedImageError

from ...exceptions import PDFDependencyError, PDFError, PDFRequestDataError
from ...renderer import ImageData
from .. import http
from ..templating import evaluate

logger = logging.getLogger("apps.pdf")

# Decompression-bomb guard: refuse images whose pixel count is excessive even
# when the encoded bytes are small.
MAX_PIXELS = 40_000_000


def normalize_image(raw: bytes, max_width: int | None = None, max_height: int | None = None):
    """Validate ``raw`` image bytes and return them as PNG ``ImageData``."""
    if len(raw) > settings.PDF_IMAGE_MAX_BYTES:
        raise PDFRequestDataError(f"Image exceeds {settings.PDF_IMAGE_MAX_BYTES} bytes.")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if probe.width * probe.height > MAX_PIXELS:
                raise PDFRequestDataError("Image dimensions are too large.")
            probe.verify()
        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            if image.mode not in ("RGB", "RGBA", "L", "LA"):
                image = image.convert("RGBA")
            if max_width or max_height:
                image.thumbnail((max_width or image.width, max_height or image.height))
            out = io.BytesIO()
            image.save(out, format="PNG", optimize=False)
            return ImageData(content=out.getvalue(), width=image.width, height=image.height)
    except PDFError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise PDFRequestDataError("Value is not a supported image.") from exc


def decode_base64_image(value: str) -> bytes:
    """Decode raw base64 or a ``data:image/...;base64,`` URI."""
    if value.startswith("data:"):
        _, _, value = value.partition(",")
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise PDFRequestDataError("Image is not valid base64.") from exc


class ImageMapper:
    """Resolve ``image`` mappings."""

    type = "image"

    def __init__(self, context=None):
        self.context = context

    def map(self, spec: dict, variables: dict):
        """Return ``ImageData`` (or ``None`` for a placeholder / empty reference)."""
        reference = evaluate(spec["source"], variables)
        if reference in (None, ""):
            if spec.get("required", False):
                raise PDFRequestDataError(f"Image for {spec.get('target')!r} is missing.")
            return None

        try:
            raw = self._load(spec.get("source_type", "url"), reference)
            return normalize_image(raw, spec.get("max_width"), spec.get("max_height"))
        except PDFDependencyError:
            if spec.get("on_error") == "placeholder":
                logger.warning(
                    "event=PDF_IMAGE_PLACEHOLDER target=%s job_id=%s",
                    spec.get("target"),
                    getattr(self.context, "job_id", ""),
                )
                return None
            raise

    def _load(self, source_type: str, reference) -> bytes:
        if source_type == "base64":
            return decode_base64_image(str(reference))
        if source_type == "file":
            return self._load_file(str(reference))
        response = http.fetch(
            "GET",
            str(reference),
            timeout=settings.PDF_IMAGE_DOWNLOAD_TIMEOUT_SECONDS,
            max_retries=settings.PDF_EXTERNAL_API_MAX_RETRIES,
            context=self.context,
            max_bytes=settings.PDF_IMAGE_MAX_BYTES,
            dependency="image",
        )
        return response.content

    @staticmethod
    def _load_file(file_id: str) -> bytes:
        from apps.files.services import FileNotFound, get_file_content

        try:
            handle = get_file_content(file_id)
        except FileNotFound as exc:
            raise PDFRequestDataError("Referenced image file does not exist.") from exc
        except Exception as exc:  # storage backend failure
            raise PDFDependencyError("Image file could not be read from storage.") from exc
        with handle:
            return handle.read(settings.PDF_IMAGE_MAX_BYTES + 1)
