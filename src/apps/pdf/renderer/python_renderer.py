"""Default pure-Python renderer, built on reportlab (spec 0016 #8, open question 1).

Input is a *resolved* document -- the output of
``apps.pdf.services.composer.compose`` -- in which every template has already
been expanded, every condition and loop evaluated, and every image or QR code
turned into ``ImageData``::

    {
      "page": {"size": "A4", "orientation": "portrait",
               "margins": {"top": 56, "right": 48, "bottom": 56, "left": 48}},
      "metadata": {"title": "...", "author": "...", "subject": "..."},
      "styles": {"default": {...}, "<name>": {...}},
      "header": {"left": "...", "center": "...", "right": "...", "line": true},
      "footer": {...},
      "sections": [[<block>, ...], ...]     # each section starts on a new page
    }

Header/footer text may contain ``{page}`` and ``{pages}``, substituted per page.
Output is deterministic for the same input (``invariant`` mode fixes the
document id and timestamps), so tests can compare bytes.
"""

from __future__ import annotations

import io
import re
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A3, A4, A5, LEGAL, LETTER, landscape, portrait
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    Image,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

from ..exceptions import PDFRenderError
from . import ImageData, PDFRenderer, fonts

PAGE_SIZES = {"A3": A3, "A4": A4, "A5": A5, "LETTER": LETTER, "LEGAL": LEGAL}
ALIGNMENTS = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT, "justify": TA_JUSTIFY}
TABLE_ALIGN = {"left": "LEFT", "center": "CENTER", "right": "RIGHT", "justify": "LEFT"}

DEFAULT_MARGINS = {"top": 56, "right": 48, "bottom": 56, "left": 48}
DEFAULT_STYLE = {
    "font": fonts.DEFAULT_FONT,
    "size": 11,
    "leading": None,
    "align": "left",
    "color": "#000000",
    "bold": False,
    "italic": False,
    "space_before": 0,
    "space_after": 6,
}
BUILTIN_STYLES = {
    "heading1": {"size": 18, "bold": True, "space_before": 6, "space_after": 10},
    "heading2": {"size": 15, "bold": True, "space_before": 6, "space_after": 8},
    "heading3": {"size": 13, "bold": True, "space_before": 4, "space_after": 6},
    "small": {"size": 9},
    "header": {"size": 9, "space_after": 0},
    "footer": {"size": 9, "space_after": 0},
}
HEADER_FOOTER_GAP = 8
PX_TO_PT = 0.75  # 96 dpi pixels to 72 dpi points

_TAG_SPLIT = re.compile(r"(<[^>]*>|&[#a-zA-Z0-9]+;)")


def with_script_fonts(markup: str, base_family: str) -> str:
    """Wrap runs of text that ``base_family`` cannot draw in a matching ``<font>``.

    Only text between tags is examined, so inline markup survives untouched.
    Fallback faces are registered regular names, which reportlab maps to the
    bold/italic face inside ``<b>``/``<i>``.
    """
    if not fonts.needs_fallback(markup) and base_family not in _script_families():
        return markup
    latin = base_family if base_family not in _script_families() else fonts.DEFAULT_FONT
    out = []
    for part in _TAG_SPLIT.split(markup):
        if not part or part.startswith("<") or (part.startswith("&") and part.endswith(";")):
            out.append(part)
            continue
        for family, text in fonts.script_runs(part, latin):
            if family == base_family:
                out.append(text)
            else:
                out.append(f'<font face="{fonts.register_family(family)}">{text}</font>')
    return "".join(out)


def _script_families() -> set[str]:
    return {family for _, _, family in fonts.SCRIPT_FONTS}


class PlaceholderBox(Flowable):
    """An empty outlined box drawn where an optional image could not be loaded."""

    def __init__(self, width: float, height: float):
        super().__init__()
        self.width, self.height = width, height

    def draw(self):
        self.canv.setStrokeColor(colors.grey)
        self.canv.setDash(2, 2)
        self.canv.rect(0, 0, self.width, self.height)


class _DecoratedCanvas(Canvas):
    """Canvas that defers page decoration until the page count is known."""

    decorate = None  # set per render: callable(canvas, page_number, page_count)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):  # noqa: N802 -- reportlab API
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for number, state in enumerate(self._pages, start=1):
            self.__dict__.update(state)
            if self.decorate is not None:
                self.decorate(self, number, total)
            super().showPage()
        super().save()


class PythonRenderer(PDFRenderer):
    """Render resolved documents with reportlab platypus."""

    def render(self, document: dict, context: dict | None = None) -> bytes:
        """Return PDF bytes for a resolved ``document``."""
        try:
            return self._render(document)
        except PDFRenderError:
            raise
        except (KeyError, ValueError, TypeError, AttributeError, OSError) as exc:
            raise PDFRenderError(f"Rendering failed: {type(exc).__name__}.") from exc

    # -- document ----------------------------------------------------------

    def _render(self, document: dict) -> bytes:
        fonts.register_all()
        self.styles = self._build_styles(document.get("styles") or {})
        page = document.get("page") or {}
        pagesize = self._page_size(page)
        margins = {**DEFAULT_MARGINS, **(page.get("margins") or {})}
        header, footer = document.get("header"), document.get("footer")

        top = margins["top"] + (self._band_height(header) if header else 0)
        bottom = margins["bottom"] + (self._band_height(footer) if footer else 0)
        metadata = document.get("metadata") or {}

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=pagesize,
            leftMargin=margins["left"],
            rightMargin=margins["right"],
            topMargin=top,
            bottomMargin=bottom,
            title=metadata.get("title", ""),
            author=metadata.get("author", ""),
            subject=metadata.get("subject", ""),
            creator="Dristi PDF service",
            producer="Dristi PDF service",
            invariant=1,
        )
        self.frame_width = doc.width

        story = []
        for index, section in enumerate(document.get("sections") or [[]]):
            if index:
                story.append(PageBreak())
            story.extend(self._blocks(section))
        if not story:
            story.append(Spacer(1, 1))

        canvas_class = type(
            "PageCanvas",
            (_DecoratedCanvas,),
            {"decorate": self._decorator(header, footer, pagesize, margins)},
        )
        doc.build(story, canvasmaker=canvas_class)
        return buffer.getvalue()

    @staticmethod
    def _page_size(page: dict):
        try:
            size = PAGE_SIZES[str(page.get("size", "A4")).upper()]
        except KeyError as exc:
            raise PDFRenderError(f"Unknown page size {page.get('size')!r}.") from exc
        if page.get("orientation", "portrait") == "landscape":
            return landscape(size)
        return portrait(size)

    # -- styles ------------------------------------------------------------

    def _build_styles(self, configured: dict) -> dict[str, ParagraphStyle]:
        base = {**DEFAULT_STYLE, **(configured.get("default") or {})}
        names = {"default", *BUILTIN_STYLES, *configured}
        styles = {}
        for name in names:
            spec = {**base, **BUILTIN_STYLES.get(name, {}), **(configured.get(name) or {})}
            styles[name] = self._paragraph_style(name, spec)
        return styles

    @staticmethod
    def _paragraph_style(name: str, spec: dict) -> ParagraphStyle:
        family = spec["font"]
        fonts.register_family(family)
        face = (
            "bold_italic"
            if spec.get("bold") and spec.get("italic")
            else "bold"
            if spec.get("bold")
            else "italic"
            if spec.get("italic")
            else "regular"
        )
        size = float(spec["size"])
        style = ParagraphStyle(
            name,
            fontName=fonts.face_name(family, face),
            fontSize=size,
            leading=float(spec.get("leading") or size * 1.3),
            alignment=ALIGNMENTS.get(spec.get("align", "left"), TA_LEFT),
            textColor=colors.HexColor(spec.get("color", "#000000")),
            spaceBefore=float(spec.get("space_before", 0)),
            spaceAfter=float(spec.get("space_after", 0)),
        )
        style.family = family
        return style

    def _style(self, name: str | None, align: str | None = None) -> ParagraphStyle:
        style = self.styles.get(name or "default")
        if style is None:
            raise PDFRenderError(f"Unknown style {name!r}.")
        if align:
            family = style.family
            style = ParagraphStyle(
                f"{style.name}-{align}", parent=style, alignment=ALIGNMENTS[align]
            )
            style.family = family
        return style

    def _paragraph(self, text: str, style: ParagraphStyle) -> Paragraph:
        return Paragraph(with_script_fonts(text or "", style.family), style)

    # -- blocks ------------------------------------------------------------

    def _blocks(self, blocks: list) -> list:
        story = []
        for block in blocks:
            story.extend(self._block(block))
        return story

    def _block(self, block: dict) -> list:
        kind = block["type"]
        if kind in ("paragraph", "text"):
            return [
                self._paragraph(block["text"], self._style(block.get("style"), block.get("align")))
            ]
        if kind == "heading":
            name = block.get("style") or f"heading{block.get('level', 1)}"
            return [self._paragraph(block["text"], self._style(name, block.get("align")))]
        if kind == "spacer":
            return [Spacer(1, float(block.get("height", 12)))]
        if kind == "page_break":
            return [PageBreak()]
        if kind == "line":
            return [
                HRFlowable(
                    width="100%",
                    thickness=float(block.get("thickness", 0.5)),
                    color=colors.HexColor(block.get("color", "#000000")),
                    spaceBefore=float(block.get("space_before", 4)),
                    spaceAfter=float(block.get("space_after", 4)),
                )
            ]
        if kind == "table":
            return [self._table(block)]
        if kind == "list":
            return [self._list(block)]
        if kind in ("image", "qr"):
            return [self._image(block)]
        raise PDFRenderError(f"Unknown block type {kind!r}.")

    def _widths(self, columns: list[dict]) -> list | None:
        widths = []
        for column in columns:
            width = column.get("width")
            if width is None:
                widths.append(None)
            elif isinstance(width, str) and width.endswith("%"):
                widths.append(self.frame_width * float(width[:-1]) / 100)
            else:
                widths.append(float(width))
        if all(width is None for width in widths):
            return None
        fixed = sum(width for width in widths if width is not None)
        free = [index for index, width in enumerate(widths) if width is None]
        if free:
            share = max(self.frame_width - fixed, 0) / len(free)
            for index in free:
                widths[index] = share
        return widths

    def _table(self, block: dict):
        columns = block.get("columns") or []
        cell_style = self._style(block.get("style"))
        header_style = self._style(block.get("header_style") or block.get("style"))
        aligns = [column.get("align", "left") for column in columns]

        rows = []
        if block.get("show_header", True) and any(column.get("header") for column in columns):
            rows.append(
                [
                    self._paragraph(
                        f"<b>{column.get('header', '')}</b>", self._aligned(header_style, aligns[i])
                    )
                    for i, column in enumerate(columns)
                ]
            )
        header_rows = len(rows)
        for row in block.get("rows") or []:
            rows.append(
                [
                    self._paragraph(
                        cell, self._aligned(cell_style, aligns[i] if i < len(aligns) else "left")
                    )
                    for i, cell in enumerate(row)
                ]
            )
        if not rows:
            return Spacer(1, 1)

        table = Table(
            rows,
            colWidths=self._widths(columns) if columns else None,
            repeatRows=header_rows if block.get("repeat_header", True) else 0,
            hAlign="LEFT",
        )
        padding = float(block.get("padding", 4))
        commands = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), padding),
            ("TOPPADDING", (0, 0), (-1, -1), padding / 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), padding / 2),
        ]
        if block.get("border", True):
            commands.append(("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#444444")))
        if header_rows and block.get("header_background"):
            commands.append(
                (
                    "BACKGROUND",
                    (0, 0),
                    (-1, header_rows - 1),
                    colors.HexColor(block["header_background"]),
                )
            )
        table.setStyle(TableStyle(commands))
        return table

    def _aligned(self, style: ParagraphStyle, align: str) -> ParagraphStyle:
        return self._style(style.name, align) if style.name in self.styles else style

    def _list(self, block: dict):
        style = self._style(block.get("style"))
        items = [
            ListItem(self._paragraph(text, style), leftIndent=float(block.get("indent", 18)))
            for text in block.get("items") or []
        ]
        ordered = block.get("ordered", False)
        return ListFlowable(
            items,
            bulletType="1" if ordered else "bullet",
            start=block.get("start", 1) if ordered else None,
            bulletFormat="%s." if ordered else None,
            bulletFontName=style.fontName,
            bulletFontSize=style.fontSize,
            leftIndent=float(block.get("indent", 18)),
        )

    def _image(self, block: dict):
        image = block.get("image")
        size = block.get("size")
        width = block.get("width", size)
        height = block.get("height", size)
        align = TABLE_ALIGN.get(block.get("align", "left"), "LEFT")

        if image is None:
            box = PlaceholderBox(float(width or 80), float(height or width or 80))
            box.hAlign = align
            return box
        if not isinstance(image, ImageData):
            raise PDFRenderError("Image block does not reference an image.")

        if width is None and height is None:
            width = min(image.width * PX_TO_PT, self.frame_width)
            height = width * image.height / image.width
        elif height is None:
            height = float(width) * image.height / image.width
        elif width is None:
            width = float(height) * image.width / image.height
        flowable = Image(io.BytesIO(image.content), width=float(width), height=float(height))
        flowable.hAlign = align
        return flowable

    # -- header / footer ---------------------------------------------------

    def _band_height(self, band: dict) -> float:
        style = self._style(band.get("style") or "header")
        return style.leading * max(1, int(band.get("lines", 1))) + HEADER_FOOTER_GAP

    def _decorator(self, header, footer, pagesize, margins):
        if not header and not footer:
            return None
        width = pagesize[0] - margins["left"] - margins["right"]

        def draw_band(canvas, band, number, total, top: bool):
            style_name = band.get("style") or ("header" if top else "footer")
            height = self._band_height(band) - HEADER_FOOTER_GAP
            if top:
                y = pagesize[1] - margins["top"] - height
            else:
                y = margins["bottom"]
            for position in ("left", "center", "right"):
                text = band.get(position)
                if not text:
                    continue
                text = text.replace("{page}", str(number)).replace("{pages}", str(total))
                paragraph = self._paragraph(text, self._style(style_name, position))
                paragraph.wrapOn(canvas, width, height)
                paragraph.drawOn(canvas, margins["left"], y)
            if band.get("line"):
                line_y = y - 2 if top else y + height + 2
                canvas.setLineWidth(0.5)
                canvas.line(margins["left"], line_y, margins["left"] + width, line_y)

        def decorate(canvas, number, total):
            canvas.saveState()
            if header:
                draw_band(canvas, header, number, total, top=True)
            if footer:
                draw_band(canvas, footer, number, total, top=False)
            canvas.restoreState()

        return staticmethod(decorate)


def escape_text(value) -> str:
    """Escape a plain string for use inside renderer markup."""
    return xml_escape("" if value is None else str(value))
