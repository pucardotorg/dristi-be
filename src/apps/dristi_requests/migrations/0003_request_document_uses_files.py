"""Store request documents through ``apps.files`` (spec 0014).

``RequestDocument.file`` changes from a ``FileField`` written straight to
storage into a foreign key to ``files.File``, and ``uploaded_by`` /
``uploaded_at`` are dropped in favour of ``File.user`` / ``File.created_at``.

Schema-only by decision: no existing document data is carried over. The table
is recreated rather than altered because a non-null foreign key cannot be added
to existing rows without a ``File`` to point them at.
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Recreate RequestDocument as a link to files.File."""

    dependencies = [
        ("dristi_requests", "0002_seed_lawyer_bar_update"),
        ("files", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.DeleteModel(name="RequestDocument"),
        migrations.CreateModel(
            name="RequestDocument",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
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
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="dristi_requests.request",
                    ),
                ),
                (
                    "file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="request_documents",
                        to="files.file",
                    ),
                ),
            ],
            options={
                "verbose_name": "Request Document",
                "verbose_name_plural": "Request Documents",
                "ordering": ("created_at",),
            },
        ),
    ]
