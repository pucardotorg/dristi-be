"""Shared fixtures for the CMS tests."""

import tomllib
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from apps.cms.models import Page, PageCategory

# Fixture TOML loaded by the ``seeded_pages`` fixture and parsed back for
# expectations — the files are the single source of truth.
SEED_DIR = Path(__file__).parent / "data"


MIGRATION_SLUGS = {"terms", "privacy", "support"}


def error_codes(response):
    """Return a standard error body as ``{field: [code, ...]}`` (spec 0000 §9.1).

    An error on the request as a whole is keyed ``None``.
    """
    codes = {}
    for error in response.json()["errors"]:
        codes.setdefault(error.get("field"), []).append(error["code"])
    return codes


def read_seed_rows(model_label):
    """Return the ``[[rows]]`` every TOML in ``SEED_DIR`` declares for ``model_label``.

    The TOML files are the single source of truth: tests validate API output
    against exactly what was seeded.
    """
    rows = []
    for path in sorted(SEED_DIR.glob("*.toml")):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        if document["seed"]["model"] == model_label:
            rows.extend(document["rows"])
    return rows


@pytest.fixture
def client():
    """An unauthenticated API client (the CMS endpoints are public)."""
    return APIClient()


@pytest.fixture
def list_url():
    """Return the pages list URL."""
    return reverse("cms-page-list")


@pytest.fixture
def slug_url():
    """Return a builder for the page-by-slug URL."""

    def build(slug):
        return reverse("cms-page-by-slug", kwargs={"slug": slug})

    return build


@pytest.fixture(scope="module")
def seeded_pages(django_db_setup, django_db_blocker):
    """Seed the fixture pages once for the whole module (spec 0025, spec 0037 §3).

    Reference data goes in the way the product loads it: through the ``seed``
    command, not through factories or ORM writes. Module scope keeps the rows
    committed outside the per-test transactions, so every test in the module
    reads the same seeded state. Promote to session scope only if a second CMS
    flow module needs the same pages.

    Committed rows are a leak the conftest must close (spec 0037 §7): the
    teardown deletes exactly what the TOML declares, so later modules that
    count pages and categories (apps/core/tests/test_seed.py) see the session
    seed untouched.
    """
    with django_db_blocker.unblock():
        call_command("seed", str(SEED_DIR), stdout=StringIO())
        yield
        pages = [row["slug"] for row in read_seed_rows("cms.Page")]
        categories = [row["slug"] for row in read_seed_rows("cms.PageCategory")]
        Page.objects.filter(slug__in=pages).delete()
        PageCategory.objects.filter(slug__in=categories).delete()
