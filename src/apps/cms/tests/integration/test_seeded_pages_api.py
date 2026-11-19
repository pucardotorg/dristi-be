"""CMS pages seeded once through the ``seed`` command, then read back over the
public GET APIs (spec 0018 §5, spec 0025, spec 0037 §3–4).

Reference data goes in the way the product loads it — ``manage.py seed`` from
TOML — and the TOML files are the single source of truth for every expected
value below.
"""

import pytest

from ..conftest import MIGRATION_SLUGS, error_codes, read_seed_rows

pytestmark = pytest.mark.django_db

SEEDED_ROWS = read_seed_rows("cms.Page")
SEEDED_CATEGORIES = {row["slug"]: row for row in read_seed_rows("cms.PageCategory")}
SEEDED_SLUGS = {row["slug"] for row in SEEDED_ROWS}

# Fields the TOML sets verbatim; validated by equality against the row.
SCALAR_FIELDS = ("slug", "title", "sub_title", "main_image_url", "content_type", "content")


def test_list_contains_the_seeded_pages(client, list_url, seeded_pages):
    """The list grows by exactly the seeded rows, envelope included."""
    response = client.get(list_url)
    assert response.status_code == 200
    body = response.json()
    assert {"count", "next", "previous", "results", "meta"} <= set(body)

    expected = MIGRATION_SLUGS | SEEDED_SLUGS
    assert body["count"] == len(expected)
    # Page size is 20, so one page holds the 3 migration + 3 seeded pages.
    assert {row["slug"] for row in body["results"]} == expected
    assert body["meta"]["spec_version"]


@pytest.mark.parametrize("row", SEEDED_ROWS, ids=[row["slug"] for row in SEEDED_ROWS])
def test_seeded_page_matches_its_toml_row(client, slug_url, seeded_pages, row):
    """Every TOML field round-trips unchanged through GET by-slug."""
    response = client.get(slug_url(row["slug"]))
    assert response.status_code == 200
    body = response.json()
    assert "meta" in body

    for field in SCALAR_FIELDS:
        assert body[field] == row[field], field
    # Server-managed fields are present; their values are not the TOML's business.
    assert body["id"]
    assert body["created_at"] and body["updated_at"]

    expected = sorted(
        (SEEDED_CATEGORIES[slug] for slug in row.get("categories", [])),
        key=lambda category: category["name"],
    )
    assert [(c["name"], c["slug"]) for c in body["categories"]] == [
        (c["name"], c["slug"]) for c in expected
    ]
    assert all(c["id"] for c in body["categories"])


def test_page_with_two_categories_resolves_each_slug(client, slug_url, seeded_pages):
    """The seed resolves every slug in a multi-category mapping (spec 0025)."""
    response = client.get(slug_url("fee-refund-policy"))
    assert response.status_code == 200
    assert [c["slug"] for c in response.json()["categories"]] == ["guides", "policies"]


def test_page_without_a_categories_key_has_none(client, slug_url, seeded_pages):
    response = client.get(slug_url("kerala-courts-overview"))
    assert response.status_code == 200
    assert response.json()["categories"] == []


def test_unseeded_slug_returns_the_standard_not_found_code(client, slug_url, seeded_pages):
    response = client.get(slug_url("seeded-nowhere"))
    assert (response.status_code, error_codes(response)) == (404, {None: ["E00105"]})
