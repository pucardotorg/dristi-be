"""QR code mapping (spec 0016 #5, ``QRMapper``).

Resolves a value and encodes it as a QR image. Mapping shape::

    {"type": "qr", "target": "verify_qr",
     "template": "https://dristi.example/verify/{{ data.case_id }}",   # or
     "source": "data.verification_url",
     "error_correction": "M", "box_size": 10, "border": 2}

The output is deterministic for the same value, so repeated renders of the
same request produce identical documents.
"""

from __future__ import annotations

import io

import qrcode
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

from ...exceptions import PDFConfigurationError, PDFRequestDataError
from ...renderer import ImageData
from ..templating import evaluate, render_text

ERROR_CORRECTION = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}

MAX_QR_PAYLOAD = 2048


def make_qr(value: str, *, error_correction: str = "M", box_size: int = 10, border: int = 2):
    """Return a PNG ``ImageData`` QR code for ``value``."""
    if not value:
        raise PDFRequestDataError("QR value is empty.")
    if len(value) > MAX_QR_PAYLOAD:
        raise PDFRequestDataError(f"QR value exceeds {MAX_QR_PAYLOAD} characters.")
    try:
        level = ERROR_CORRECTION[error_correction]
    except KeyError as exc:
        raise PDFConfigurationError(f"Unknown QR error correction {error_correction!r}.") from exc

    code = qrcode.QRCode(error_correction=level, box_size=int(box_size), border=int(border))
    code.add_data(value)
    code.make(fit=True)
    image = code.make_image(fill_color="black", back_color="white").get_image()
    out = io.BytesIO()
    image.save(out, format="PNG")
    return ImageData(content=out.getvalue(), width=image.width, height=image.height)


class QRMapper:
    """Resolve ``qr`` mappings."""

    type = "qr"

    def map(self, spec: dict, variables: dict):
        """Return the QR ``ImageData`` for the resolved value."""
        if "template" in spec:
            value = render_text(spec["template"], variables, escape_output=False)
        else:
            value = evaluate(spec["source"], variables)
        if value in (None, "") and not spec.get("required", True):
            return None
        return make_qr(
            "" if value is None else str(value),
            error_correction=spec.get("error_correction", "M"),
            box_size=spec.get("box_size", 10),
            border=spec.get("border", 2),
        )
