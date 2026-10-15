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

    def test_unknown_slug_returns_404(self, client):
        response = client.get(slug_url("does-not-exist"))
        assert response.status_code == 404


@pytest.mark.django_db
class TestSchema:
    """The OpenAPI schema exposes the CMS endpoints under the CMS tag."""

    def test_schema_has_cms_tag_and_pages_path(self, client):
        response = client.get("/api/schema/?format=json")
        assert response.status_code == 200
        schema = response.json()
        assert "/api/v1/cms/pages/" in schema["paths"]
        assert "CMS" in schema["paths"]["/api/v1/cms/pages/"]["get"]["tags"]
