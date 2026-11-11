"""Tests for resolve_request_language (spec 0030 section 5)."""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.api.errors import get_error
from apps.core.languages import parse_accept_language, resolve_request_language
from apps.core.models import Language


def resolve(params=None, accept_language=None):
    headers = {"HTTP_ACCEPT_LANGUAGE": accept_language} if accept_language is not None else {}
    return resolve_request_language(RequestFactory().get("/", params or {}, **headers)).code


class LanguageEchoView(APIView):
    """A minimal language-aware endpoint, as a consumer would write one."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"code": resolve_request_language(request).code})


def call_view(params=None, accept_language=None):
    headers = {"HTTP_ACCEPT_LANGUAGE": accept_language} if accept_language is not None else {}
    request = APIRequestFactory().get("/api/v1/echo/", params or {}, **headers)
    response = LanguageEchoView.as_view()(request)
    response.render()
    return response


@pytest.mark.django_db
class TestResolutionOrder:
    def test_default_when_nothing_requested(self):
        assert resolve() == "en"

    def test_lang_param(self):
        assert resolve({"lang": "ml"}) == "ml"

    def test_lang_param_is_case_insensitive(self):
        assert resolve({"lang": "ML"}) == "ml"

    def test_lang_beats_accept_language(self):
        assert resolve({"lang": "hi"}, "ml") == "hi"

    def test_accept_language_beats_default(self):
        assert resolve(accept_language="ml") == "ml"

    def test_quality_values_are_honoured(self):
        assert resolve(accept_language="ml;q=0.5, hi;q=0.9, en;q=0.1") == "hi"

    def test_equal_quality_keeps_header_order(self):
        assert resolve(accept_language="hi, ml") == "hi"

    def test_region_falls_back_to_primary_subtag(self):
        assert resolve(accept_language="ml-IN") == "ml"

    def test_exact_match_preferred_over_primary_subtag(self):
        Language.objects.create(code="en-in", name="English (India)", native_name="English")
        assert resolve(accept_language="en-IN") == "en-in"

    def test_unknown_tags_are_skipped(self):
        assert resolve(accept_language="fr-FR, de;q=0.9, hi;q=0.5") == "hi"

    @pytest.mark.parametrize(
        "header",
        [
            "fr",
            "*",
            "garbage;;;",
            "ml;q=0",
            "ml;q=abc",
            "ml;q=2",
            "en_IN",
            ";q=0.5",
            ",,",
            "x" * 600,
        ],
    )
    def test_unknown_or_malformed_header_falls_back_to_default(self, header):
        assert resolve(accept_language=header) == "en"

    def test_malformed_element_does_not_spoil_the_rest(self):
        assert resolve(accept_language="ml;q=bad, hi;q=0.4") == "hi"

    def test_inactive_language_is_not_negotiated(self):
        Language.objects.filter(code="ml").update(is_active=False)
        assert resolve(accept_language="ml, hi;q=0.5") == "hi"

    def test_lang_param_surrounding_whitespace_is_ignored(self):
        assert resolve({"lang": " ml "}) == "ml"

    def test_without_default_a_match_still_resolves(self):
        Language.objects.filter(is_default=True).update(is_default=False)
        assert resolve(accept_language="ml") == "ml"

    def test_without_default_fallback_is_a_configuration_error(self):
        Language.objects.filter(is_default=True).update(is_default=False)
        with pytest.raises(ImproperlyConfigured):
            resolve(accept_language="fr")

    def test_works_with_drf_requests(self):
        response = call_view({"lang": "ml"}, "hi")
        assert response.status_code == status.HTTP_200_OK
        assert response.data == {"code": "ml"}


@pytest.mark.django_db
class TestUnsupportedLangParam:
    @pytest.mark.parametrize("value", ["xx", "", "en_IN"])
    def test_unknown_lang_is_rejected(self, value):
        response = call_view({"lang": value})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        [error] = response.data["errors"]
        assert error["code"] == "E10001"
        assert error["field"] == "lang"

    def test_message_names_the_requested_code(self):
        response = call_view({"lang": "xx"})
        assert response.data["errors"][0]["message"] == 'Language "xx" is not supported.'

    def test_error_code_is_registered_in_core_domain(self):
        error = get_error("E10001")
        assert error.domain == "core"
        assert error.status == status.HTTP_400_BAD_REQUEST

    def test_inactive_lang_is_rejected(self):
        Language.objects.filter(code="hi").update(is_active=False)
        response = call_view({"lang": "hi"}, "ml")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        [error] = response.data["errors"]
        assert error["code"] == "E10001"
        assert error["field"] == "lang"


class TestParseAcceptLanguage:
    def test_orders_by_quality_and_lowercases(self):
        assert parse_accept_language("en-US;q=0.8, ML, hi;q=0.9, *;q=0.1") == [
            "ml",
            "hi",
            "en-us",
        ]

    def test_whitespace_and_quality_formats(self):
        assert parse_accept_language(" ml ; q=0.500 ,hi;Q=1.0, ta;q=.5, kn;q=1.5") == ["hi", "ml"]

    def test_empty(self):
        assert parse_accept_language("") == []
