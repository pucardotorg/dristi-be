"""ExternalAPIMapper and the shared HTTP helper (#5, #10, #13)."""

from unittest.mock import patch

import pytest
import requests

from apps.pdf.exceptions import PDFConfigurationError, PDFDependencyError, PDFRequestDataError
from apps.pdf.services.context import RequestContext
from apps.pdf.services.mapping.external_api import ExternalAPIMapper

CONTEXT = RequestContext(tenant_id="kl", locale="ml_IN", correlation_id="corr-9")


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def close(self):
        pass


SPEC = {
    "type": "external_api",
    "target": "advocate",
    "url": "https://hrms.example/advocates/{{ data.advocate_id }}",
    "params": {"tenant": "{{ meta.tenant_id }}"},
    "path": "$.advocate",
    "fields": {"name": "$.name", "bar": "$.barNo"},
}
VARIABLES = {"data": {"advocate_id": "a 1&x"}, "meta": CONTEXT.as_dict()}
PAYLOAD = {"advocate": {"name": "Adv. Rao", "barNo": "K/1/2000"}}


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("apps.pdf.services.http.time.sleep"):
        yield


def run(spec=SPEC, variables=VARIABLES, response=None, side_effect=None):
    with patch(
        "apps.pdf.services.http.requests.request",
        return_value=response or FakeResponse(payload=PAYLOAD),
        side_effect=side_effect,
    ) as request:
        value = ExternalAPIMapper(CONTEXT).map(spec, variables)
    return value, request


def test_get_with_templated_url_params_and_field_projection():
    value, request = run()

    assert value == {"name": "Adv. Rao", "bar": "K/1/2000"}
    args, kwargs = request.call_args
    assert args == ("GET", "https://hrms.example/advocates/a 1&x")  # not HTML-escaped
    assert kwargs["params"] == {"tenant": "kl"}
    assert kwargs["timeout"] == (10, 10)
    assert kwargs["headers"]["X-Tenant-Id"] == "kl"
    assert kwargs["headers"]["X-Correlation-Id"] == "corr-9"
    assert "Authorization" not in kwargs["headers"]


def test_post_sends_params_as_json_body():
    _, request = run({**SPEC, "method": "POST"})
    assert request.call_args.kwargs["json"] == {"tenant": "kl"}
    assert request.call_args.kwargs["params"] is None


def test_service_credentials_come_from_settings(settings):
    settings.PDF_SERVICE_CREDENTIALS = {"hrms": {"Authorization": "Bearer svc"}}
    _, request = run({**SPEC, "credentials": "hrms"})
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer svc"


def test_unknown_credentials_are_a_configuration_error():
    with pytest.raises(PDFConfigurationError):
        run({**SPEC, "credentials": "missing"})


def test_many_returns_a_list():
    payload = {"items": [{"n": 1}, {"n": 2}]}
    spec = {"target": "ns", "url": "https://x.example/", "path": "$.items[*].n", "many": True}
    value, _ = run(spec, response=FakeResponse(payload=payload))
    assert value == [1, 2]


def test_identical_requests_share_one_call():
    mapper = ExternalAPIMapper(CONTEXT)
    with patch(
        "apps.pdf.services.http.requests.request", return_value=FakeResponse(payload=PAYLOAD)
    ) as request:
        mapper.map(SPEC, VARIABLES)
        mapper.map({**SPEC, "target": "again", "fields": {"name": "$.name"}}, VARIABLES)
    assert request.call_count == 1


def test_call_budget_per_job(settings):
    settings.PDF_EXTERNAL_API_MAX_CALLS_PER_JOB = 1
    mapper = ExternalAPIMapper(CONTEXT)
    with patch(
        "apps.pdf.services.http.requests.request", return_value=FakeResponse(payload=PAYLOAD)
    ):
        mapper.map(SPEC, VARIABLES)
        with pytest.raises(PDFRequestDataError):
            mapper.map(SPEC, {**VARIABLES, "data": {"advocate_id": "other"}})


def test_5xx_and_timeouts_are_retried_then_raise_dependency_error(settings):
    settings.PDF_EXTERNAL_API_MAX_RETRIES = 2
    with pytest.raises(PDFDependencyError):
        run(side_effect=[requests.Timeout(), FakeResponse(503), requests.ConnectionError()])


def test_transient_failure_then_success():
    value, request = run(side_effect=[FakeResponse(502), FakeResponse(payload=PAYLOAD)])
    assert value["name"] == "Adv. Rao"
    assert request.call_count == 2


def test_4xx_is_not_retried():
    with pytest.raises(PDFRequestDataError):
        _, request = run(response=FakeResponse(404))


def test_non_json_response_is_a_dependency_error():
    with pytest.raises(PDFDependencyError):
        run(response=FakeResponse(payload=ValueError("bad json")))


def test_missing_value_without_default_raises():
    with pytest.raises(PDFRequestDataError):
        run(response=FakeResponse(payload={}))


def test_missing_value_uses_default():
    value, _ = run({**SPEC, "default": None, "required": False}, response=FakeResponse(payload={}))
    assert value is None


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://x.example/", "/relative"])
def test_non_http_urls_are_refused(url):
    with pytest.raises(PDFRequestDataError):
        run({**SPEC, "url": url})


def test_host_allow_list(settings):
    settings.PDF_FETCH_ALLOWED_HOSTS = ["allowed.example"]
    with pytest.raises(PDFRequestDataError):
        run()
