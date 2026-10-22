"""PythonRenderer, composer, fonts, merge and split (#8)."""

import io

import pytest
from pypdf import PdfReader

from apps.pdf.exceptions import PDFRenderError
from apps.pdf.renderer import ImageData
from apps.pdf.renderer.fonts import script_runs
from apps.pdf.renderer.merge import merge, page_count, split
from apps.pdf.renderer.python_renderer import PythonRenderer, with_script_fonts
from apps.pdf.services.composer import compose
from apps.pdf.services.mapping.qr import make_qr
from apps.pdf.tests.factories import png_bytes, simple_pdf


def render(document):
    return PythonRenderer().render(document, {})


def text_of(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


def doc(*blocks, **extra):
    return {"sections": [list(blocks)], **extra}


def test_text_blocks_and_inline_markup():
    pdf = render(
        doc(
            {"type": "heading", "text": "Summons", "level": 1, "align": "center"},
            {"type": "paragraph", "text": "To <b>Asha</b>, <i>respondent</i>."},
            {"type": "line"},
            {"type": "spacer", "height": 20},
        )
    )
    assert pdf.startswith(b"%PDF-")
    text = text_of(pdf)
    assert "Summons" in text and "To Asha, respondent." in text


def test_output_is_deterministic():
    document = doc({"type": "paragraph", "text": "Same"})
    assert render(document) == render(document)


def test_table_with_widths_and_repeated_header_across_pages():
    rows = [[str(index), f"Name {index}"] for index in range(120)]
    pdf = render(
        doc(
            {
                "type": "table",
                "columns": [
                    {"header": "No", "width": 40},
                    {"header": "Name", "width": "50%", "align": "right"},
                ],
                "rows": rows,
                "header_background": "#eeeeee",
            }
        )
    )
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) > 1
    for page in reader.pages:
        assert "No" in page.extract_text().split("\n")[0]
    assert "Name 119" in text_of(pdf)


def test_lists():
    pdf = render(doc({"type": "list", "items": ["First", "Second"], "ordered": True}))
    text = text_of(pdf)
    assert "1." in text and "First" in text and "Second" in text


def test_images_qr_and_placeholders():
    image = ImageData(content=png_bytes(40, 20), width=40, height=20)
    pdf = render(
        doc(
            {"type": "image", "image": image, "width": 80},
            {"type": "qr", "image": make_qr("https://x.example"), "size": 60, "align": "right"},
            {"type": "image", "image": None, "width": 50, "height": 30},
        )
    )
    page = PdfReader(io.BytesIO(pdf)).pages[0]
    assert len(page.images) == 2


def test_page_breaks_sections_headers_and_footers():
    pdf = render(
        {
            "page": {"size": "A5", "orientation": "landscape", "margins": {"top": 30}},
            "header": {"left": "Court", "right": "Page {page} of {pages}", "line": True},
            "footer": {"center": "Footer text"},
            "sections": [
                [{"type": "paragraph", "text": "One"}, {"type": "page_break"}],
                [{"type": "paragraph", "text": "Two"}],
            ],
        }
    )
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 3
    width, height = float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)
    assert width > height
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        assert f"Page {number} of 3" in text and "Footer text" in text


def test_indic_text_uses_script_fonts_and_survives_extraction():
    pdf = render(doc({"type": "paragraph", "text": "Summons സമൻസ് and समन"}))
    text = text_of(pdf)
    assert "സമൻസ്" in text and "समन" in text
    fonts = {
        str(font)
        for page in PdfReader(io.BytesIO(pdf)).pages
        for font in page["/Resources"]["/Font"].values()
        for font in [font.get_object()["/BaseFont"]]
    }
    assert any("Malayalam" in font for font in fonts)
    assert any("Devanagari" in font for font in fonts)


def test_script_runs_keep_neutral_characters_together():
    assert script_runs("A, സമൻസ് 12, B", "noto-sans") == [
        ("noto-sans", "A, "),
        ("noto-sans-malayalam", "സമൻസ് 12, "),
        ("noto-sans", "B"),
    ]


def test_script_fallback_preserves_markup():
    out = with_script_fonts("<b>സ</b> &amp; x", "noto-sans")
    assert out.startswith("<b><font face=") and "&amp;" in out


def test_custom_styles_and_fonts():
    pdf = render(
        doc(
            {"type": "paragraph", "text": "Styled", "style": "notice"},
            styles={"notice": {"font": "noto-sans-malayalam", "size": 14, "color": "#aa0000"}},
        )
    )
    assert "Styled" in text_of(pdf)


@pytest.mark.parametrize(
    "document",
    [
        doc({"type": "unknown"}),
        doc({"type": "paragraph", "text": "x", "style": "missing"}),
        {"page": {"size": "B9"}, "sections": [[]]},
        doc({"type": "image", "image": "not image data"}),
    ],
)
def test_invalid_documents_raise_render_error(document):
    with pytest.raises(PDFRenderError):
        render(document)


def test_composer_escapes_request_data_but_keeps_template_markup():
    format_config = {"body": [{"type": "paragraph", "text": "<b>{{ data.name }}</b>"}]}
    document = compose(format_config, {"data": {"name": "<i>x</i> & y"}, "meta": {}})
    assert document["sections"][0][0]["text"] == "<b>&lt;i&gt;x&lt;/i&gt; &amp; y</b>"


def test_composer_conditions_loops_and_groups():
    format_config = {
        "header": {"center": "{{ title }} {page}"},
        "body": [
            {"type": "paragraph", "text": "hidden", "when": "not show"},
            {"type": "list", "source": "xs", "as": "x", "item": "{{ loop.index }}:{{ x }}"},
            {
                "type": "group",
                "source": "xs",
                "as": "x",
                "blocks": [{"type": "paragraph", "text": "{{ x }}", "when": "loop.last"}],
            },
            {"type": "qr", "value": "https://x/{{ title }}"},
        ],
    }
    document = compose(format_config, {"show": True, "xs": ["a", "b"], "title": "T"})
    blocks = document["sections"][0]
    assert document["header"]["center"] == "T {page}"
    assert blocks[0] == {"type": "list", "items": ["1:a", "2:b"]}
    assert blocks[1] == {"type": "paragraph", "text": "b"}
    assert isinstance(blocks[2]["image"], ImageData)


def test_merge_and_split():
    merged = merge([simple_pdf(2, "A"), simple_pdf(3, "B")])
    assert page_count(merged) == 5
    parts = split(merged, 2)
    assert [page_count(part) for part in parts] == [2, 2, 1]
    assert "B 3" in text_of(parts[-1])


def test_merge_rejects_invalid_input():
    with pytest.raises(PDFRenderError):
        merge([simple_pdf(), b"not a pdf"])
    with pytest.raises(PDFRenderError):
        merge([])
