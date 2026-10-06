"""QRMapper (#5)."""

import io

import pytest
from PIL import Image

from apps.pdf.exceptions import PDFConfigurationError, PDFRequestDataError
from apps.pdf.services.mapping.qr import MAX_QR_PAYLOAD, QRMapper, make_qr


def test_template_value_is_encoded_without_html_escaping():
    variables = {"data": {"id": "a&b"}}
    image = QRMapper().map({"template": "https://x.example/v?id={{ data.id }}"}, variables)
    assert image.content == make_qr("https://x.example/v?id=a&b").content


def test_source_expression():
    image = QRMapper().map({"source": "url"}, {"url": "https://x.example"})
    with Image.open(io.BytesIO(image.content)) as decoded:
        assert decoded.format == "PNG"
        assert decoded.size == (image.width, image.height)


def test_output_is_deterministic():
    assert make_qr("same").content == make_qr("same").content
    assert make_qr("same").content != make_qr("different").content


def test_error_correction_changes_density():
    low = make_qr("x" * 50, error_correction="L")
    high = make_qr("x" * 50, error_correction="H")
    assert high.width > low.width


def test_empty_value_is_rejected_unless_optional():
    with pytest.raises(PDFRequestDataError):
        QRMapper().map({"source": "v"}, {"v": ""})
    assert QRMapper().map({"source": "v", "required": False}, {"v": ""}) is None


def test_oversized_value_is_rejected():
    with pytest.raises(PDFRequestDataError):
        make_qr("x" * (MAX_QR_PAYLOAD + 1))


def test_unknown_error_correction_is_a_configuration_error():
    with pytest.raises(PDFConfigurationError):
        make_qr("x", error_correction="Z")
