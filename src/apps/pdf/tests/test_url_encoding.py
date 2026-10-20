"""URL templates encode every inserted value (external API mappings).

Written against several URL shapes -- path segments, nested paths, query
values -- because the rule must not depend on any particular endpoint.
"""

from unittest.mock import patch
from urllib.parse import urlsplit

import pytest
from django.core.exceptions import ValidationError

from apps.pdf.exceptions import PDFConfigurationError, PDFRequestDataError
from apps.pdf.services.context import RequestContext
from apps.pdf.services.mapping.external_api import ExternalAPIMapper
from apps.pdf.services.templating import encode_url_value, render_url
from apps.pdf.services.validation import validate_data_config


class FakeResponse:
    status_code = 200
    headers = {}

    def json(self):
        return {"ok": True}

    def close(self):
        pass


def requested_url(url_template, data):
    spec = {"type": "external_api", "target": "x", "url": url_template, "path": "$.ok"}
    with patch("apps.pdf.services.http.requests.request", return_value=FakeResponse()) as request:
        ExternalAPIMapper(RequestContext(tenant_id="kl")).map(spec, {"data": data, "meta": {}})
    return request.call_args.args[1]


@pytest.mark.parametrize(
    ("template", "data", "expected"),
    [
        # a single path segment
        (
            "https://api.example/advocates/{{ data.v }}",
            {"v": "KL/123/2020"},
            "https://api.example/advocates/KL%2F123%2F2020",
        ),
        # several segments in a deeper path, each value stays one segment
        (
            "https://api.example/cases/{{ data.t }}/{{ data.n }}/orders",
            {"t": "CC", "n": "12/2026"},
            "https://api.example/cases/CC/12%2F2026/orders",
        ),
        # a value in the query string cannot add parameters or a fragment
        (
            "https://api.example/search?q={{ data.v }}&limit=5",
            {"v": "a&b=c#d"},
            "https://api.example/search?q=a%26b%3Dc%23d&limit=5",
        ),
        # values in the host-independent middle of a path
        (
            "https://api.example/v1/{{ data.v }}.json",
            {"v": "x y"},
            "https://api.example/v1/x%20y.json",
        ),
        # unreserved characters pass through unchanged
        (
            "https://api.example/items/{{ data.v }}",
            {"v": "Ab-1_2.3~4"},
            "https://api.example/items/Ab-1_2.3~4",
        ),
        # non-ASCII is UTF-8 percent-encoded
        (
            "https://api.example/names/{{ data.v }}",
            {"v": "സമൻസ്"},
            "https://api.example/names/%E0%B4%B8%E0%B4%AE%E0%B5%BB%E0%B4%B8%E0%B5%8D",
        ),
        # numbers and loops/conditionals still work; literal text is kept
        (
            "https://api.example/p/{{ data.n }}{% if data.f %}/flag{% endif %}",
            {"n": 7, "f": 1},
            "https://api.example/p/7/flag",
        ),
    ],
)
def test_values_are_encoded_whatever_the_url_shape(template, data, expected):
    assert requested_url(template, data) == expected


@pytest.mark.parametrize("value", ["#frag", "?admin=1", "a/../../admin", "../secret"])
def test_values_cannot_truncate_or_navigate(value):
    url = requested_url("https://api.example/records/{{ data.v }}/detail", {"v": value})
    parts = urlsplit(url)
    assert parts.fragment == "" and parts.query == ""
    assert parts.path.startswith("/records/") and parts.path.endswith("/detail")
    assert parts.path.count("/") == 3  # exactly the template's three separators


@pytest.mark.parametrize("value", ["@evil.example", "evil.example:80@x", "//evil.example"])
def test_values_cannot_change_the_host(value):
    url = requested_url("https://api.example/{{ data.v }}", {"v": value})
    assert urlsplit(url).hostname == "api.example"


@pytest.mark.parametrize("value", [".", ".."])
def test_dot_segments_are_rejected(value):
    with pytest.raises(PDFRequestDataError):
        render_url("https://api.example/a/{{ v }}/b", {"v": value})


def test_url_path_opt_in_keeps_separators_but_encodes_segments():
    url = render_url("https://api.example/files/{{ p | url_path }}", {"p": "orders/2026/a b#1"})
    assert url == "https://api.example/files/orders/2026/a%20b%231"


@pytest.mark.parametrize("value", ["../etc", "a/../b", "a//b", "/abs", "a/."])
def test_url_path_rejects_navigation_and_empty_segments(value):
    with pytest.raises(PDFRequestDataError):
        render_url("https://api.example/files/{{ p | url_path }}", {"p": value})


def test_a_host_from_data_is_encoded_not_followed():
    url = render_url("{{ base }}/x", {"base": "https://evil.example"})
    assert url == "https%3A%2F%2Fevil.example/x"
    with pytest.raises(PDFRequestDataError):
        requested_url("{{ data.base }}/x", {"base": "https://evil.example"})


def test_literal_urls_are_returned_unchanged():
    assert render_url("https://api.example/a?b=1&c=2", {}) == "https://api.example/a?b=1&c=2"


def test_missing_value_is_a_request_error():
    with pytest.raises(PDFRequestDataError):
        render_url("https://api.example/{{ data.missing }}", {"data": {}})


def test_invalid_url_template_is_a_configuration_error():
    with pytest.raises(PDFConfigurationError):
        render_url("https://api.example/{{ x", {})


def test_encode_url_value_treats_none_as_empty():
    assert encode_url_value(None) == ""


def test_query_params_are_left_to_requests():
    spec = {
        "type": "external_api",
        "target": "x",
        "url": "https://api.example/search",
        "params": {"q": "{{ data.v }}"},
        "path": "$.ok",
    }
    with patch("apps.pdf.services.http.requests.request", return_value=FakeResponse()) as request:
        ExternalAPIMapper(RequestContext(tenant_id="kl")).map(
            spec, {"data": {"v": "a&b"}, "meta": {}}
        )
    # Passed raw: requests performs the query-string encoding exactly once.
    assert request.call_args.kwargs["params"] == {"q": "a&b"}


def test_url_path_filter_is_accepted_by_config_validation():
    validate_data_config(
        {
            "mappings": [
                {
                    "type": "external_api",
                    "target": "x",
                    "url": "https://api.example/{{ data.p | url_path }}",
                }
            ]
        }
    )
    with pytest.raises(ValidationError):
        validate_data_config(
            {
                "mappings": [
                    {
                        "type": "external_api",
                        "target": "x",
                        "url": "https://api.example/{{ data.p | nope }}",
                    }
                ]
            }
        )
