"""Add ``Request.request_number`` and its counter (spec 0010 section 1.1).

The column is added nullable, existing requests are numbered in creation
order, the counter is moved past them, and the column is then made non-null
and unique.
"""

import re
import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

STATE_CODE_PATTERN = re.compile(r"^[A-Z]{2,3}$")
# Only used when the configuration row is not seeded yet; never at runtime.
FALLBACK_STATE_CODE = "KL"


def state_code(apps):
    """Return the configured state code, or the fallback with a warning."""
    Configuration = apps.get_model("core", "Configuration")
    value = (
        Configuration.objects.filter(config_set="tenant", config_key="state_code", is_active=True)
        .values_list("config_value", flat=True)
        .first()
    )
    value = (value or "").strip().upper()
    if STATE_CODE_PATTERN.match(value):
        return value
    print(
        f"\n  tenant.state_code is not configured; numbering existing requests "
        f"with {FALLBACK_STATE_CODE}."
    )
    return FALLBACK_STATE_CODE


def backfill(apps, schema_editor):
    """Number existing requests in creation order and set the counter."""
    Request = apps.get_model("dristi_requests", "Request")
    RequestNumberSequence = apps.get_model("dristi_requests", "RequestNumberSequence")

    requests = Request.objects.order_by("created_at", "id").only("id")
    if not requests.exists():
        return

    prefix = f"{state_code(apps)}-REQ"
    value = 0
    for value, request in enumerate(requests.iterator(), start=1):
        Request.objects.filter(pk=request.pk).update(request_number=f"{prefix}-{value:05d}")
    RequestNumberSequence.objects.create(prefix=prefix, value=value)


class Migration(migrations.Migration):
    """Add the request number, its counter and backfill existing requests."""

    dependencies = [
        ("core", "0005_configuration"),
        ("dristi_requests", "0003_request_document_uses_files"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RequestNumberSequence",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("prefix", models.CharField(max_length=16, unique=True)),
                ("value", models.PositiveIntegerField(default=0)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_created_by",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="%(app_label)s_%(class)s_updated_by",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
                "abstract": False,
            },
        ),
        migrations.AddField(
            model_name="request",
            name="request_number",
            field=models.CharField(editable=False, max_length=32, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="request",
            name="request_number",
            field=models.CharField(editable=False, max_length=32, unique=True),
        ),
    ]
