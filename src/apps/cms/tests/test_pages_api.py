"""API tests for the public, read-only CMS pages endpoints."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.fixture
def client():
    """An unauthenticated API client (endpoints are public)."""
    return APIClient()


def list_url():
    """Return the pages list URL."""
    return reverse("cms-page-list")


def slug_url(slug):
    """Return the page-by-slug URL."""
    return reverse("cms-page-by-slug", kwargs={"slug": slug})


@pytest.mark.django_db
class TestPagesListAPI:
    """GET /api/v1/cms/pages/."""

    def test_list_is_public_paginated_with_meta(self, client):
        response = client.get(list_url())
        assert response.status_code == 200
        body = response.json()
        # Project pagination shape.
        assert {"count", "next", "previous", "results"} <= set(body)
        assert body["count"] >= 3
        # Response envelope.
        assert body["meta"]["spec_version"]


@pytest.mark.django_db
class TestPageBySlugAPI:
    """GET /api/v1/cms/pages/slug/{slug}/."""

    def test_existing_slug_returns_200(self, client):
        response = client.get(slug_url("terms"))
        assert response.status_code == 200
        body = response.json()
        assert body["slug"] == "terms"
        assert body["categories"][0]["slug"] == "main"
        assert "meta" in body

    def test_unknown_slug_returns_404_with_error_body(self, client):
        response = client.get(slug_url("does-not-exist"))
        assert response.status_code == 404
        # Project-standard error envelope: {"errors": [{"code", "message"}], ...}.
        body = response.json()
        assert body["errors"][0]["message"]

    def test_invalid_slug_in_url_returns_404(self, client):
        # "about_us" has an underscore, so it fails the slug route regex and
        # resolves to nothing rather than reaching the view.
        response = client.get(list_url() + "slug/about_us/")
        assert response.status_code == 404


@pytest.mark.django_db
class TestPagesAreReadOnly:
    """Only GET is allowed; write verbs are rejected."""

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_write_methods_rejected(self, client, method):
        response = getattr(client, method)(list_url())
        assert response.status_code == 405


@pytest.mark.django_db
class TestSchema:
    """The OpenAPI schema exposes both CMS endpoints under the CMS tag."""

    def test_schema_has_cms_tag_and_pages_path(self, client):
        response = client.get("/api/schema/?format=json")
        assert response.status_code == 200
        schema = response.json()

        list_path = "/api/v1/cms/pages/"
        slug_path = "/api/v1/cms/pages/slug/{slug}/"
        assert list_path in schema["paths"]
        assert slug_path in schema["paths"]
        assert "CMS" in schema["paths"][list_path]["get"]["tags"]
        assert "CMS" in schema["paths"][slug_path]["get"]["tags"]

    def test_schema_has_no_id_retrieve_route(self, client):
        # Spec 0018 section 5 lists only list and by-slug; no id-based retrieve.
        schema = client.get("/api/schema/?format=json").json()
        assert "/api/v1/cms/pages/{id}/" not in schema["paths"]
