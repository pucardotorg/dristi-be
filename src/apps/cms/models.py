"""CMS models for simple, read-mostly content pages (spec 0018)."""

import re

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel

# Page slugs are intentionally stricter than Django's default slug: no
# underscores, spaces or other punctuation — only letters, digits and hyphens.
# Used with fullmatch(): "$" would also accept a trailing newline.
SLUG_RE = re.compile(r"[A-Za-z0-9-]+")


def validate_page_slug(value):
    """Reject a slug containing anything but letters, digits and hyphens."""
    # fullmatch, not match: with "$" anchoring, match() accepts a trailing
    # newline ("terms\n"), which would never match the slug URL route and so
    # could never be fetched again.
    if not SLUG_RE.fullmatch(value or ""):
        raise ValidationError(
            "Slug may contain only letters, digits and hyphens "
            "(no '_', spaces or special characters)."
        )


class PageCategory(BaseModel):
    """A category used to group CMS pages."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        """Meta options."""

        ordering = ("name",)
        verbose_name = "Page Category"
        verbose_name_plural = "Page Categories"

    def __str__(self):
        """Return the category name for admin and logs."""
        return self.name


class Page(BaseModel):
    """A simple CMS content page, served read-only by its unique slug."""

    class ContentType(models.TextChoices):
        """Supported content formats (only markdown for v1)."""

        MARKDOWN = "markdown", "Markdown"

    slug = models.CharField(
        max_length=150,
        unique=True,
        db_index=True,
        validators=[validate_page_slug],
    )
    title = models.CharField(max_length=255)
    sub_title = models.CharField(max_length=255, blank=True)
    main_image_url = models.URLField(max_length=500, blank=True)
    content_type = models.CharField(
        max_length=30,
        choices=ContentType.choices,
        default=ContentType.MARKDOWN,
    )
    content = models.TextField()
    categories = models.ManyToManyField(
        PageCategory,
        related_name="pages",
        blank=True,
    )

    class Meta:
        """Meta options."""

        ordering = ("title", "slug")
        verbose_name = "Page"
        verbose_name_plural = "Pages"

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.title} ({self.slug})"

    def clean(self):
        """Normalise the slug to lowercase before validation.

        Slugs are case-insensitive identifiers. Postgres uniqueness is
        case-sensitive, so without this "Terms" and "terms" could coexist as
        two different pages.
        """
        super().clean()
        if self.slug:
            self.slug = self.slug.lower()

    def save(self, *args, **kwargs):
        """Persist a canonical lowercase slug on every write path."""
        if self.slug:
            self.slug = self.slug.lower()
        super().save(*args, **kwargs)
