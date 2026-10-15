"""LocalizationMapper / LocalizationService (#5)."""

from unittest.mock import patch

import pytest
import requests

from apps.pdf.exceptions import PDFDependencyError
from apps.pdf.services.context import RequestContext
from apps.pdf.services.mapping.localization import LocalizationMapper, LocalizationService

INLINE = {
    "module": "pdf",
    "messages": {"en_IN": {"SUMMONS": "Summons"}, "ml_IN": {"SUMMONS": "സമൻസ്"}},
}


def mapper(locale="en_IN", inline=INLINE):
    context = RequestContext(tenant_id="kl", locale=locale, correlation_id="corr-1")
    return LocalizationMapper(LocalizationService(inline, context))


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload

    def close(self):
        pass


def test_inline_message_for_request_locale():
    assert mapper().map({"code": "SUMMONS"}, {}) == "Summons"
    assert mapper("ml_IN").map({"code": "SUMMONS"}, {}) == "സമൻസ്"


def test_explicit_locale_overrides_request_locale():
    assert mapper().map({"code": "SUMMONS", "locale": "ml_IN"}, {}) == "സമൻസ്"


def test_source_expression_and_lists():
    variables = {"codes": ["SUMMONS", "UNKNOWN"]}
    assert mapper().map({"source": "codes"}, variables) == ["Summons", "UNKNOWN"]


def test_missing_message_uses_default_with_code():
    assert mapper().map({"code": "X1", "default": "[{code}]"}, {}) == "[X1]"


def test_no_remote_lookup_without_base_url(settings):
    settings.PDF_LOCALIZATION_BASE_URL = ""
    with patch("apps.pdf.services.http.requests.request") as request:
        assert mapper().map({"code": "OTHER"}, {}) == "OTHER"
    request.assert_not_called()


def test_remote_lookup_is_cached_per_tenant_module_locale(settings):
    settings.PDF_LOCALIZATION_BASE_URL = "https://l10n.example/messages"
    payload = {"messages": [{"code": "COURT", "message": "Court"}]}
    with patch(
        "apps.pdf.services.http.requests.request", return_value=FakeResponse(payload=payload)
    ) as request:
        assert mapper(inline={}).map({"code": "COURT", "module": "common"}, {}) == "Court"
        # A new service instance (next job) is served from the Django cache.
        assert mapper(inline={}).map({"code": "COURT", "module": "common"}, {}) == "Court"

    request.assert_called_once()
    kwargs = request.call_args.kwargs
    assert kwargs["params"] == {"tenant_id": "kl", "module": "common", "locale": "en_IN"}
    assert kwargs["headers"]["X-Tenant-Id"] == "kl"
    assert kwargs["headers"]["X-Correlation-Id"] == "corr-1"
    assert kwargs["headers"]["Accept-Language"] == "en-IN"


def test_remote_failure_raises_dependency_error(settings):
    settings.PDF_LOCALIZATION_BASE_URL = "https://l10n.example/messages"
    settings.PDF_EXTERNAL_API_MAX_RETRIES = 1
    with (
        patch("apps.pdf.services.http.time.sleep"),
        patch("apps.pdf.services.http.requests.request", side_effect=requests.Timeout()) as request,
        pytest.raises(PDFDependencyError),
    ):
        mapper(inline={}).map({"code": "COURT"}, {})
    assert request.call_count == 2
