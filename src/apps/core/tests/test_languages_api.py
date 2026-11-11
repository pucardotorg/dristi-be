"""Tests for GET /api/v1/languages/ (spec 0030 section 4)."""

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.core.models import Language

URL = reverse("language-list")

requires_postgres = pytest.mark.skipif(
    connection.vendor != "postgresql", reason="JSONField contains needs PostgreSQL"
)


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def extra_languages():
    Language.objects.create(
        code="ta", name="Tamil", native_name="தமிழ்", sort_order=5, supports=["ocr"]
    )
    Language.objects.create(
        code="kn", name="Kannada", native_name="ಕನ್ನಡ", sort_order=1, is_active=False
    )


@pytest.mark.django_db
class TestLanguageList:
    def test_public_paginated_list_of_active_languages(self, client, extra_languages):
        response = client.get(URL)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert set(body) == {"count", "next", "previous", "results", "meta"}
        assert body["count"] == 4
        assert body["next"] is None
        assert body["previous"] is None
        assert [item["code"] for item in body["results"]] == ["en", "ta", "ml", "hi"]

    def test_exposes_exactly_the_contract_fields(self, client):
        results = client.get(URL).json()["results"]
        assert results[0] == {
            "code": "en",
            "name": "English",
            "native_name": "English",
            "is_default": True,
            "supports": ["ui"],
        }
        assert all(
            set(item) == {"code", "name", "native_name", "is_default", "supports"}
            for item in results
        )

    def test_uses_standard_page_size(self, client):
        Language.objects.bulk_create(
            Language(code=f"x{chr(97 + i)}", name=f"L{i}", native_name=f"L{i}", sort_order=100)
            for i in range(20)
        )
        body = client.get(URL).json()
        assert body["count"] == 23
        assert len(body["results"]) == 20
        assert body["next"] is not None
        page_two = client.get(URL, {"page": 2}).json()
        assert len(page_two["results"]) == 3

    @requires_postgres
    def test_filter_by_capability(self, client, extra_languages):
        response = client.get(URL, {"supports": "ui"})
        assert response.status_code == status.HTTP_200_OK
        assert [item["code"] for item in response.json()["results"]] == ["en", "ml", "hi"]

        response = client.get(URL, {"supports": "ocr"})
        assert [item["code"] for item in response.json()["results"]] == ["ta"]

        response = client.get(URL, {"supports": "translation"})
        assert response.json()["count"] == 0

    def test_invalid_capability_is_rejected(self, client):
        response = client.get(URL, {"supports": "bogus"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        [error] = response.json()["errors"]
        assert error["code"] == "E00005"
        assert error["field"] == "supports"

    def test_no_retrieve_or_write_routes(self, client):
        language = Language.objects.get(code="en")
        assert client.get(f"{URL}{language.pk}/").status_code == status.HTTP_404_NOT_FOUND
        for method in (client.post, client.put, client.patch, client.delete):
            assert method(URL, {"code": "ta"}).status_code == status.HTTP_405_METHOD_NOT_ALLOWED

    def test_empty_capability_is_no_filter(self, client):
        response = client.get(URL, {"supports": ""})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 3

    def test_capability_is_case_sensitive(self, client):
        response = client.get(URL, {"supports": "UI"})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["errors"][0]["code"] == "E00005"

    def test_page_out_of_range_is_not_found(self, client):
        response = client.get(URL, {"page": 99})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["errors"][0]["code"] == "E00105"

    def test_open_to_users_who_have_not_finished_registration(self, client):
        # The project default permissions would refuse this user.
        user = get_user_model().objects.create_user(
            mobile_number="+919000000013", name="new", email="new@example.com", password="x"
        )
        client.force_authenticate(user)
        assert client.get(URL).status_code == status.HTTP_200_OK

    def test_repeated_list_is_served_from_cache(self, client):
        client.get(URL)
        with CaptureQueriesContext(connection) as cached:
            response = client.get(URL)
        assert response.status_code == status.HTTP_200_OK
        assert len(cached.captured_queries) == 0

        Language.objects.filter(code="hi").update(is_active=False)
        assert client.get(URL).json()["count"] == 2


@pytest.mark.django_db
class TestLanguageSchema:
    def test_schema_documents_endpoint_under_core_tag(self, client):
        schema = client.get(reverse("api-schema"), {"format": "json"}).json()
        operation = schema["paths"]["/api/v1/languages/"]["get"]
        assert operation["tags"] == ["core"]
        assert {param["name"] for param in operation["parameters"]} >= {"page", "supports"}
        examples = operation["responses"]["400"]["content"]["application/json"]["examples"]
        assert any(
            example["value"]["errors"][0]
            == {
                "code": "E00005",
                "message": '"bogus" is not a valid choice.',
                "field": "supports",
            }
            for example in examples.values()
        )
        assert "/api/v1/languages/{id}/" not in schema["paths"]
