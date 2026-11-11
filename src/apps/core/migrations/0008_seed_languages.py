"""Seed the initial supported languages (spec 0030 section 10)."""

from django.db import migrations

LANGUAGES = (
    {
        "code": "en",
        "name": "English",
        "native_name": "English",
        "is_default": True,
        "sort_order": 0,
        "is_active": True,
        "supports": ["ui"],
    },
    {
        "code": "ml",
        "name": "Malayalam",
        "native_name": "മലയാളം",
        "is_default": False,
        "sort_order": 10,
        "is_active": True,
        "supports": ["ui"],
    },
    {
        "code": "hi",
        "name": "Hindi",
        "native_name": "हिन्दी",
        "is_default": False,
        "sort_order": 20,
        "is_active": True,
        "supports": ["ui"],
    },
)


def seed_languages(apps, schema_editor):
    Language = apps.get_model("core", "Language")
    for language in LANGUAGES:
        defaults = {key: value for key, value in language.items() if key != "code"}
        Language.objects.update_or_create(code=language["code"], defaults=defaults)


def unseed_languages(apps, schema_editor):
    Language = apps.get_model("core", "Language")
    Language.objects.filter(code__in=[language["code"] for language in LANGUAGES]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_language"),
    ]

    operations = [
        migrations.RunPython(seed_languages, unseed_languages),
    ]
