"""Model-level tests for the CMS app."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.cms.models import Page, PageCategory, validate_page_slug


class TestSlugValidator:
    """validate_page_slug accepts clean slugs and rejects the rest."""

    @pytest.mark.parametrize("value", ["about-us", "page1", "terms"])
    def test_accepts_valid(self, value):
        validate_page_slug(value)  # must not raise

    @pytest.mark.parametrize("value", ["about_us", "about us", "about@us"])
    def test_rejects_invalid(self, value):
        with pytest.raises(ValidationError):
            validate_page_slug(value)


@pytest.mark.django_db
class TestPageModel:
    """DB-level constraints and model validation."""

    def test_unique_slug_enforced(self):
        Page.objects.create(slug="terms-x", title="A", content="x")
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Page.objects.create(slug="terms-x", title="B", content="y")

    def test_full_clean_rejects_bad_slug(self):
        page = Page(slug="bad_slug", title="T", content="c")
        with pytest.raises(ValidationError):
            page.full_clean()


@pytest.mark.django_db
class TestSeedData:
    """The seed migration populated the default categories and pages."""

    def test_categories_seeded(self):
        slugs = set(PageCategory.objects.values_list("slug", flat=True))
        assert {"help", "main", "faq"} <= slugs

    def test_pages_seeded_and_mapped_to_main(self):
        main = PageCategory.objects.get(slug="main")
        for slug in ("terms", "privacy", "support"):
            page = Page.objects.get(slug=slug)
            assert main in page.categories.all()
