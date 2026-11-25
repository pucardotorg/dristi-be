"""PythonRenderer, composer, fonts, merge and split (#8)."""

import io

import pytest
from pypdf import PdfReader

from apps.pdf.exceptions import PDFRenderError, PDFRequestDataError
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


def test_signature_slots_two_to_a_row_report_where_each_box_is():
    """One slot per signatory, two to a row; each box's position is reported (efiling DOC-02)."""
    from apps.pdf.services.signing import prepare_for_signing

    filler = [{"type": "paragraph", "text": "Affidavit text"}] * 45
    signers = [{"key": f"s{i}", "name": f"Signer {i} <b>", "label": f"Role {i}"} for i in range(5)]
    document = compose(
        {"body": [*filler, {"type": "signatures", "source": "signers", "box_height": 60}]},
        {"signers": signers},
    )

    pdf, anchors = PythonRenderer().render_with_anchors(document, {})

    assert list(anchors) == [f"s{i}" for i in range(5)]
    # Paired left and right on one line, the odd one out alone on its own row.
    assert anchors["s0"]["y"] == anchors["s1"]["y"] and anchors["s0"]["x"] < anchors["s1"]["x"]
    assert anchors["s2"]["y"] == anchors["s3"]["y"] < anchors["s1"]["y"]
    assert anchors["s4"]["x"] == anchors["s0"]["x"]
    text = text_of(pdf)
    # Names come from request data and are escaped, never read as markup.
    assert "Signer 0 <b>" in text and "Role 4" in text
    for anchor in anchors.values():
        assert anchor["height"] == 60
        prepare_for_signing(pdf, dict(anchor))


def test_signatures_block_needs_a_list_of_signatories():
    with pytest.raises(Exception, match="not a list of signatories"):
        compose({"body": [{"type": "signatures", "source": "signers"}]}, {"signers": "x"})


def test_a_renderer_without_anchors_reports_none():
    """The base renderer's ``render_with_anchors`` falls back to ``render`` with no anchors."""
    from apps.pdf.renderer import PDFRenderer

    class Plain(PDFRenderer):
        def render(self, document, context):
            return b"%PDF-plain"

    assert Plain().render_with_anchors({}, {}) == (b"%PDF-plain", {})


def test_signer_names_in_indic_scripts_use_script_fonts():
    """A Malayalam or Devanagari signer name draws with its script's font, as body text does."""
    malayalam, devanagari = "രാജേഷ് കുമാർ", "राजेश कुमार"
    document = compose(
        {"body": [{"type": "signatures", "source": "signers"}]},
        {
            "signers": [
                {"key": "a", "name": malayalam, "label": "Complainant 1"},
                {"key": "b", "name": devanagari, "label": "Complainant 2"},
            ]
        },
    )

    pdf, _ = PythonRenderer().render_with_anchors(document, {})

    page = PdfReader(io.BytesIO(pdf)).pages[0]
    fonts = {font.get_object()["/BaseFont"] for font in page["/Resources"]["/Font"].values()}
    assert any("NotoSansMalayalam" in name for name in fonts)
    assert any("NotoSansDevanagari" in name for name in fonts)
    text = page.extract_text()
    assert malayalam in text and devanagari in text
    assert "\x00" not in text


# -- composer edge cases ------------------------------------------------------


def test_composer_refuses_a_loop_over_something_that_is_not_a_list():
    with pytest.raises(PDFRequestDataError, match="is not a list"):
        compose({"body": [{"type": "list", "source": "items"}]}, {"items": 5})


def test_composer_treats_a_missing_loop_source_as_empty():
    document = compose({"body": [{"type": "list", "source": "items"}]}, {"items": None})

    assert document["sections"][0][0]["items"] == []


def test_composer_refuses_an_image_source_that_is_not_an_image():
    with pytest.raises(PDFRequestDataError, match="does not resolve to an image"):
        compose({"body": [{"type": "image", "source": "seal"}]}, {"seal": "not-an-image"})


def test_composer_draws_a_qr_from_a_value_and_checks_a_qr_source():
    document = compose(
        {"body": [{"type": "qr", "value": "https://x/{{ id }}", "size": 60}]}, {"id": "A1"}
    )
    block = document["sections"][0][0]
    assert isinstance(block["image"], ImageData) and "value" not in block

    with pytest.raises(PDFRequestDataError, match="does not resolve to a QR image"):
        compose({"body": [{"type": "qr", "source": "code"}]}, {"code": "text"})


def test_compose_many_needs_at_least_one_record():
    from apps.pdf.services.composer import compose_many

    with pytest.raises(PDFRequestDataError, match="no records"):
        compose_many({"body": []}, [])


def test_an_empty_document_still_renders_one_page():
    pdf = render(doc())

    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_merging_one_document_returns_it_unchanged():
    single = simple_pdf()

    assert merge([single]) is single


def test_split_needs_at_least_one_page_per_part():
    with pytest.raises(PDFRenderError, match="at least 1"):
        split(simple_pdf(), 0)


def test_an_unknown_font_family_is_refused():
    from apps.pdf.renderer.fonts import register_family

    with pytest.raises(KeyError, match="Unknown font family"):
        register_family("no-such-font")


def test_a_broken_filename_template_falls_back_to_the_key_and_entity():
    from apps.pdf.services.config_loader import LoadedConfig
    from apps.pdf.services.generator import document_filename

    config = LoadedConfig("v", "case-complaint", 1, {"body": []}, {"filename": "{{ missing.x }}"})

    name = document_filename(config, {"meta": {"entity_id": "C1"}}, suffix="part-1")

    assert name == "case-complaint-C1-part-1.pdf"


def test_a_format_config_the_composer_cannot_apply_is_a_configuration_error():
    from apps.pdf.exceptions import PDFConfigurationError
    from apps.pdf.services.config_loader import LoadedConfig
    from apps.pdf.services.generator import render_variables

    # A table without columns passes no schema here and breaks the composer.
    config = LoadedConfig("v", "k", 1, {"body": [{"type": "table"}]}, {})

    with pytest.raises(PDFConfigurationError, match="could not be applied"):
        render_variables(config, [{}])


def test_signature_names_are_bold_and_roles_take_the_label_style():
    """As the efiling §16.9 sample: the signer's name in bold, the role in the label style."""
    document = compose(
        {
            "styles": {"label": {"size": 7.5, "color": "#555555"}},
            "body": [{"type": "signatures", "source": "s", "label_style": "label"}],
        },
        {"s": [{"key": "a", "name": "Rajesh Kumar", "label": "Complainant 1"}]},
    )

    pdf, _ = PythonRenderer().render_with_anchors(document, {})

    found = {}

    def visit(text, cm, tm, font, size):
        if text.strip() and font:
            found.setdefault(text.strip(), (font["/BaseFont"], round(size * tm[0], 1)))

    PdfReader(io.BytesIO(pdf)).pages[0].extract_text(visitor_text=visit)
    assert "Bold" in found["Rajesh Kumar"][0]
    assert found["Complainant 1"][1] == 7.5
