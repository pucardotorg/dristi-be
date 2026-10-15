"""Seed default CMS categories and pages (spec 0018 section 10)."""

from django.db import migrations

CATEGORIES = [
    {"name": "Help", "slug": "help"},
    {"name": "Main", "slug": "main"},
    {"name": "FAQ", "slug": "faq"},
]

PAGES = [
    {"slug": "terms", "title": "Terms of Use"},
    {"slug": "privacy", "title": "Privacy"},
    {"slug": "support", "title": "Support"},
]


def seed(apps, schema_editor):
    """Create the default categories and pages, each page mapped to ``Main``."""
    PageCategory = apps.get_model("cms", "PageCategory")
    Page = apps.get_model("cms", "Page")

    categories = {}
    for data in CATEGORIES:
        category, _ = PageCategory.objects.update_or_create(
            slug=data["slug"],
            defaults={"name": data["name"]},
        )
        categories[data["slug"]] = category

    main = categories["main"]
    for data in PAGES:
        page, _ = Page.objects.update_or_create(
            slug=data["slug"],
            defaults={
                "title": data["title"],
                "content_type": "markdown",
                "content": f"# {data['title']}\n\nDummy markdown content.",
            },
        )
        page.categories.add(main)


def unseed(apps, schema_editor):
    """Remove the seeded pages and categories (reverse migration)."""
    PageCategory = apps.get_model("cms", "PageCategory")
    Page = apps.get_model("cms", "Page")
    Page.objects.filter(slug__in=[p["slug"] for p in PAGES]).delete()
    PageCategory.objects.filter(slug__in=[c["slug"] for c in CATEGORIES]).delete()


class Migration(migrations.Migration):
    """Data migration seeding the default CMS content."""

    dependencies = [
        ("cms", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
