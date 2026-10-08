"""Font registry for the renderer (spec 0016 #8).

Fonts ship with the app under ``renderer/fonts`` (Noto, SIL OFL 1.1; see
``fonts/OFL.txt``) and are declared in the single ``PDF_FONTS`` mapping below.
A ``format_config`` refers to a font family by its key. Every family has a
regular and bold face; ``italic``/``bold_italic`` fall back to those when a
script has no italic design.

Indic fonts carry no Latin glyphs, and Latin fonts carry no Indic glyphs,
while court documents routinely mix the two. ``script_runs`` therefore splits
text into runs per script so each run is drawn with a family that has its
glyphs. Complex-script shaping (conjuncts, reordering) is done by reportlab
through HarfBuzz (``uharfbuzz``).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).resolve().parent / "fonts"

DEFAULT_FONT = "noto-sans"

PDF_FONTS: dict[str, dict[str, str]] = {
    "noto-sans": {
        "regular": "NotoSans-Regular.ttf",
        "bold": "NotoSans-Bold.ttf",
        "italic": "NotoSans-Italic.ttf",
        "bold_italic": "NotoSans-BoldItalic.ttf",
    },
    "noto-sans-malayalam": {
        "regular": "NotoSansMalayalam-Regular.ttf",
        "bold": "NotoSansMalayalam-Bold.ttf",
    },
    "noto-sans-devanagari": {
        "regular": "NotoSansDevanagari-Regular.ttf",
        "bold": "NotoSansDevanagari-Bold.ttf",
    },
}

# Unicode blocks -> the family that renders them. Anything else uses the
# family requested by the block (normally Latin).
SCRIPT_FONTS: tuple[tuple[int, int, str], ...] = (
    (0x0900, 0x097F, "noto-sans-devanagari"),
    (0xA8E0, 0xA8FF, "noto-sans-devanagari"),
    (0x0D00, 0x0D7F, "noto-sans-malayalam"),
)

# Characters every script shares; they stay in the surrounding run so that a
# space or comma does not split a Malayalam phrase into separate runs.
_NEUTRAL = set(" \t\n,.;:!?()[]{}'\"-–—/\\|0123456789\u200c\u200d")

FACES = ("regular", "bold", "italic", "bold_italic")


def face_name(family: str, face: str = "regular") -> str:
    """Return the reportlab font name registered for a family face."""
    return f"{family}:{face}"


@cache
def register_family(family: str) -> str:
    """Register every face of ``family`` with reportlab and return its regular name."""
    try:
        files = PDF_FONTS[family]
    except KeyError as exc:
        raise KeyError(f"Unknown font family {family!r}.") from exc

    resolved = {
        "regular": files["regular"],
        "bold": files.get("bold", files["regular"]),
        "italic": files.get("italic", files["regular"]),
        "bold_italic": files.get("bold_italic", files.get("bold", files["regular"])),
    }
    for face, filename in resolved.items():
        pdfmetrics.registerFont(TTFont(face_name(family, face), str(FONT_DIR / filename)))

    regular = face_name(family)
    addMapping(regular, 0, 0, regular)
    addMapping(regular, 1, 0, face_name(family, "bold"))
    addMapping(regular, 0, 1, face_name(family, "italic"))
    addMapping(regular, 1, 1, face_name(family, "bold_italic"))
    return regular


def register_all() -> None:
    """Register every declared family (cheap after the first call)."""
    for family in PDF_FONTS:
        register_family(family)


def font_for_char(char: str) -> str | None:
    """Return the family required to draw ``char``, or ``None`` for the default."""
    code = ord(char)
    for start, end, family in SCRIPT_FONTS:
        if start <= code <= end:
            return family
    return None


def script_runs(text: str, default_family: str) -> list[tuple[str, str]]:
    """Split ``text`` into ``(family, text)`` runs by script.

    Neutral characters (spaces, punctuation, digits, joiners) join the current
    run, so mixed text produces as few runs as possible.
    """
    runs: list[list] = []
    for char in text:
        if char in _NEUTRAL and runs:
            runs[-1][1] += char
            continue
        family = font_for_char(char) or default_family
        if runs and runs[-1][0] == family:
            runs[-1][1] += char
        else:
            runs.append([family, char])
    return [(family, chunk) for family, chunk in runs]


def needs_fallback(text: str) -> bool:
    """Whether ``text`` contains any character that needs a script font."""
    return any(font_for_char(char) for char in text)
