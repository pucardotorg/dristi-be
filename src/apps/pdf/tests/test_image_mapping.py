"""ImageMapper (#5, #10)."""

import base64
import io
from unittest.mock import patch

import pytest
import requests
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.files.models import FileType
from apps.files.services import upload_file
from apps.pdf.exceptions import PDFDependencyError, PDFRequestDataError
from apps.pdf.renderer import ImageData
from apps.pdf.services.mapping.image import ImageMapper
from apps.pdf.tests.factories import make_user, png_bytes


class FakeResponse:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content

    def iter_content(self, chunk_size=1):
        yield self.content

    def close(self):
        pass


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("apps.pdf.services.http.time.sleep"):
        yield


def as_jpeg(width=30, height=20):
    out = io.BytesIO()
    Image.new("RGB", (width, height), (0, 128, 0)).save(out, format="JPEG")
    return out.getvalue()


def test_base64_image_is_normalized_to_png():
    encoded = "data:image/jpeg;base64," + base64.b64encode(as_jpeg()).decode()
    image = ImageMapper().map({"source": "img", "source_type": "base64"}, {"img": encoded})

    assert isinstance(image, ImageData)
    assert (image.width, image.height) == (30, 20)
    assert image.content.startswith(b"\x89PNG")


def test_image_is_downscaled_to_max_dimensions():
    encoded = base64.b64encode(png_bytes(400, 200)).decode()
    spec = {"source": "img", "source_type": "base64", "max_width": 100}
    image = ImageMapper().map(spec, {"img": encoded})
    assert (image.width, image.height) == (100, 50)


def test_url_image_is_fetched_with_image_timeout(settings):
    settings.PDF_IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 3
    with patch(
        "apps.pdf.services.http.requests.request", return_value=FakeResponse(png_bytes())
    ) as request:
        image = ImageMapper().map({"source": "'https://img.example/seal.png'"}, {})
    assert image.width == 20
    assert request.call_args.kwargs["timeout"] == (3, 3)
    assert request.call_args.kwargs["stream"] is True


def test_oversized_download_is_rejected(settings):
    settings.PDF_IMAGE_MAX_BYTES = 10
    response = FakeResponse(png_bytes(), headers={"Content-Length": "5000"})
    with (
        patch("apps.pdf.services.http.requests.request", return_value=response),
        pytest.raises(PDFRequestDataError),
    ):
        ImageMapper().map({"source": "'https://img.example/big.png'"}, {})


def test_failed_download_raises_dependency_error():
    with (
        patch("apps.pdf.services.http.requests.request", side_effect=requests.Timeout()),
        pytest.raises(PDFDependencyError),
    ):
        ImageMapper().map({"source": "'https://img.example/x.png'"}, {})


def test_failed_download_can_fall_back_to_placeholder():
    spec = {"source": "'https://img.example/x.png'", "on_error": "placeholder"}
    with patch("apps.pdf.services.http.requests.request", side_effect=requests.Timeout()):
        assert ImageMapper().map(spec, {}) is None


def test_non_image_bytes_are_rejected():
    encoded = base64.b64encode(b"definitely not an image").decode()
    with pytest.raises(PDFRequestDataError):
        ImageMapper().map({"source": "img", "source_type": "base64"}, {"img": encoded})


def test_invalid_base64_is_rejected():
    with pytest.raises(PDFRequestDataError):
        ImageMapper().map({"source": "img", "source_type": "base64"}, {"img": "***"})


def test_empty_reference_is_none_unless_required():
    assert ImageMapper().map({"source": "img"}, {"img": ""}) is None
    with pytest.raises(PDFRequestDataError):
        ImageMapper().map({"source": "img", "required": True}, {"img": None})


@pytest.mark.django_db
def test_file_reference_is_read_through_apps_files():
    upload = SimpleUploadedFile("seal.png", png_bytes(), content_type="image/png")
    file_id = upload_file(
        {"user_id": make_user().pk, "files": [{"file": upload, "file_type": FileType.IMAGE}]}
    )["files"][0]["id"]

    image = ImageMapper().map({"source": "fid", "source_type": "file"}, {"fid": str(file_id)})
    assert image.width == 20


@pytest.mark.django_db
def test_missing_file_reference_is_a_request_error():
    with pytest.raises(PDFRequestDataError):
        ImageMapper().map(
            {"source": "fid", "source_type": "file"},
            {"fid": "00000000-0000-0000-0000-000000000000"},
        )
