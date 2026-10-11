"""Tests for the India Post pincode lookup, with the HTTP call mocked."""

from unittest.mock import MagicMock, patch

import pytest
import requests
from django.core.cache import cache
from django.test import override_settings

from apps.address.services import (
    PincodeDetails,
    PincodeNotFoundError,
    PincodeServiceUnavailableError,
    lookup_pincode,
)

GET = "apps.address.services.requests.get"

SUCCESS_BODY = [
    {
        "Message": "Number of pincode(s) found:2",
        "Status": "Success",
        "PostOffice": [
            {"Name": "Bangalore G.P.O.", "District": "Bangalore", "State": "Karnataka"},
            {"Name": "Vidhana Soudha", "District": "Bangalore", "State": "Karnataka"},
        ],
    }
]
NOT_FOUND_BODY = [{"Message": "No records found", "Status": "Error", "PostOffice": None}]


def fake_response(body=None, status_code=200, json_error=None):
    """Return a stand-in for ``requests.Response``."""
    response = MagicMock(status_code=status_code)
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = body
    return response


@pytest.fixture(autouse=True)
def clear_cache():
    """Start every test with no cached lookups."""
    cache.clear()
    yield
    cache.clear()


class TestLookupSuccess:
    """India Post answers with a known pincode."""

    def test_returns_district_and_state(self):
        with patch(GET, return_value=fake_response(SUCCESS_BODY)):
            details = lookup_pincode("560001")

        assert details == PincodeDetails(pincode="560001", district="Bangalore", state="Karnataka")

    @override_settings(
        PINCODE_API_URL="https://pincode.example/{pincode}",
        PINCODE_API_TIMEOUT=3,
    )
    def test_calls_the_configured_url_with_a_timeout(self):
        with patch(GET, return_value=fake_response(SUCCESS_BODY)) as get:
            lookup_pincode("560001")

        get.assert_called_once_with("https://pincode.example/560001", timeout=3)

    def test_trims_whitespace_in_the_answer(self):
        body = [
            {
                "Status": "Success",
                "PostOffice": [{"District": " Bangalore ", "State": "Karnataka\n"}],
            }
        ]
        with patch(GET, return_value=fake_response(body)):
            details = lookup_pincode("560001")

        assert (details.district, details.state) == ("Bangalore", "Karnataka")

    def test_success_is_cached(self):
        with patch(GET, return_value=fake_response(SUCCESS_BODY)) as get:
            lookup_pincode("560001")
            lookup_pincode("560001")

        assert get.call_count == 1

    def test_cached_answer_survives_the_api_going_down(self):
        with patch(GET, return_value=fake_response(SUCCESS_BODY)):
            first = lookup_pincode("560001")

        with patch(GET, side_effect=requests.ConnectionError):
            assert lookup_pincode("560001") == first


class TestLookupNotFound:
    """India Post answers, and the pincode is unknown."""

    def test_error_status_is_not_found(self):
        with (
            patch(GET, return_value=fake_response(NOT_FOUND_BODY)),
            pytest.raises(PincodeNotFoundError),
        ):
            lookup_pincode("999999")

    def test_success_with_no_post_offices_is_not_found(self):
        body = [{"Status": "Success", "PostOffice": []}]
        with patch(GET, return_value=fake_response(body)), pytest.raises(PincodeNotFoundError):
            lookup_pincode("999999")

    def test_not_found_is_not_cached(self):
        with patch(GET, return_value=fake_response(NOT_FOUND_BODY)) as get:
            for _ in range(2):
                with pytest.raises(PincodeNotFoundError):
                    lookup_pincode("999999")

        assert get.call_count == 2


class TestLookupUnavailable:
    """India Post cannot be reached or answers with something unusable."""

    @pytest.mark.parametrize(
        "error",
        [requests.Timeout, requests.ConnectionError, requests.TooManyRedirects],
    )
    def test_request_failure_is_unavailable(self, error):
        with patch(GET, side_effect=error), pytest.raises(PincodeServiceUnavailableError):
            lookup_pincode("560001")

    @pytest.mark.parametrize("status_code", [404, 429, 500, 502, 503])
    def test_non_200_status_is_unavailable(self, status_code):
        response = fake_response(SUCCESS_BODY, status_code=status_code)
        with patch(GET, return_value=response), pytest.raises(PincodeServiceUnavailableError):
            lookup_pincode("560001")

    def test_non_json_body_is_unavailable(self):
        response = fake_response(json_error=ValueError("not json"))
        with patch(GET, return_value=response), pytest.raises(PincodeServiceUnavailableError):
            lookup_pincode("560001")

    @pytest.mark.parametrize(
        "body",
        [
            [],
            {},
            None,
            [{"Message": "no status"}],
            [{"Status": "Success", "PostOffice": [{"Name": "no district or state"}]}],
            [{"Status": "Success", "PostOffice": [{"District": None, "State": "Karnataka"}]}],
            [{"Status": "Success", "PostOffice": [{"District": "", "State": "Karnataka"}]}],
        ],
    )
    def test_malformed_body_is_unavailable(self, body):
        with (
            patch(GET, return_value=fake_response(body)),
            pytest.raises(PincodeServiceUnavailableError),
        ):
            lookup_pincode("560001")

    def test_failure_is_not_cached(self):
        with (
            patch(GET, side_effect=requests.Timeout),
            pytest.raises(PincodeServiceUnavailableError),
        ):
            lookup_pincode("560001")

        with patch(GET, return_value=fake_response(SUCCESS_BODY)):
            assert lookup_pincode("560001").district == "Bangalore"
