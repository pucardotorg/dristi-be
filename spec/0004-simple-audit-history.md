# 0004 — Simple Audit History

## Status
Proposed

## Context
Dristi needs a complete, queryable audit trail for domain models so operators can answer:

- What did a record look like at a specific point in time?
- Who changed it, when, and what fields were modified?
- When was a record created, updated, or (soft) deleted?

The existing `BaseModel` provides `created_at` and `updated_at` timestamps but does not retain
prior values of fields or the user responsible for each change.

## Goals

- Provide a reusable abstract model `BaseAuditableModel` that any model can inherit to automatically
  receive a complete historical record table.
- Store every create, update, and delete as a versioned snapshot.
- Record the user responsible for each change when a request context is available.
- Keep the implementation opt-in so models that do not need history are unaffected.
- Support administrative inspection and API-level querying of an object's history.

## Non-goals

- Field-level diff UI in the admin (out of scope; the history table itself is sufficient).
- Automatic reverting through the API (admin revert is acceptable).
- Tracking related many-to-many through tables unless explicitly enabled.
- Replacing `created_by`/`updated_by` on `BaseModel` (see ADR 0002); history stores the same
  information per change and is complementary.

## Decision

Use [`django-simple-history`](https://django-simple-history.readthedocs.io/) to generate a
`<ModelName>_historical` table for every concrete model that opts in.

## Proposed changes

### 1. Dependency

Add `django-simple-history` to the project dependencies.

```toml
# pyproject.toml
[project]
dependencies = [
    "Django>=5.0",
    "djangorestframework>=3.14",
    "django-simple-history>=3.4.0",
    # ... existing dependencies
]
```

Install and lock:

```bash
pip install django-simple-history>=3.4.0
```

### 2. Settings

Add `simple_history` to `INSTALLED_APPS` in `src/config/settings/base.py`:

```python
INSTALLED_APPS = [
    # ... existing apps
    "simple_history",
    # ... project apps
]
```

Register the middleware so the current user is captured automatically during requests:

```python
MIDDLEWARE = [
    # ... existing middleware
    "simple_history.middleware.HistoryRequestMiddleware",
]
```

Disable admin revert to prevent accidental restoration of historical records:

```python
SIMPLE_HISTORY_REVERT_DISABLED = True
```

The middleware records `request.user` as `history_user` on every historical record created during
that request.

### 3. `BaseAuditableModel` abstract model

Location: `src/apps/core/models.py`

```python
from simple_history.models import HistoricalRecords

from apps.core.models import BaseModel


class BaseAuditableModel(BaseModel):
    """Abstract base model that captures a full history table for every change."""

    history = HistoricalRecords(inherit=True)

    class Meta:
        abstract = True
```

`inherit=True` allows subclasses that define their own `history` manager to override it while still
inheriting the historical-tracking behavior from the abstract parent.

### 4. Model migration

For every concrete model that switches to `BaseAuditableModel`, run:

```bash
cd src && python manage.py makemigrations <app>
```

django-simple-history will generate an additional migration for the new `<Model>_historical` table.

Example migration for a `Document` model:

```python
# apps/core/migrations/0002_historicaldocument.py
class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="HistoricalDocument",
            fields=[
                ("id", models.UUIDField(db_index=True, default=uuid.uuid4, editable=False)),
                ("title", models.CharField(max_length=255)),
                # ... copies of all tracked fields
                ("history_id", models.AutoField(primary_key=True, serialize=False)),
                ("history_date", models.DateTimeField(db_index=True)),
                ("history_change_reason", models.CharField(max_length=100, null=True)),
                ("history_type", models.CharField(max_length=1, choices=[("+", "Created"), ("~", "Changed"), ("-", "Deleted")])),
                ("history_user", models.ForeignKey(null=True, on_delete=models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "historical document",
                "verbose_name_plural": "historical documents",
                "ordering": ("-history_date", "-history_id"),
                "get_latest_by": "history_date",
            },
            bases=(simple_history.models.HistoricalChanges, models.Model),
        ),
    ]
```

### 5. Usage example

```python
# apps/core/models.py
from apps.core.models import BaseAuditableModel


class Document(BaseAuditableModel):
    title = models.CharField(max_length=255)
    body = models.TextField()


# apps/users/models.py
class User(BaseAuditableModel, AbstractUser):
    email = models.EmailField(unique=True)
```

Any model that does **not** need history continues to inherit from `BaseModel` only.

### 6. Capturing the user

#### 6.1 During requests

`HistoryRequestMiddleware` sets `history_user` automatically when a request is present.

#### 6.2 Outside requests

In Dramatiq actors, management commands, or imports, create/update records inside a
`HistoryRequestMiddleware` context or set the user manually:

```python
from simple_history.utils import update_change_reason

# Set the user explicitly
document.title = "New title"
document.save()
document.history.latest().history_user = system_user
document.history.latest().save()

# Or pass a change reason
update_change_reason(document, "Batch title update from importer")
```

For bulk creates/updates, use `bulk_create_with_history` / `bulk_update_with_history`:

```python
from simple_history.utils import bulk_create_with_history

bulk_create_with_history(documents, Document, batch_size=500)
```

### 7. Change reasons

Use `update_change_reason` to annotate why a change happened, especially for programmatic updates.

```python
from simple_history.utils import update_change_reason

obj.save()
update_change_reason(obj, "Approved by manager via API")
```

### 8. Admin integration

Register the history view for auditable models:

```python
# apps/core/admin.py
from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.models import Document


@admin.register(Document)
class DocumentAdmin(SimpleHistoryAdmin):
    list_display = ("title", "created_at", "updated_at")
```

This adds a "History" button on each object's change page in the Django admin.

### 9. API exposure

Expose a read-only nested history endpoint per resource:

```python
# apps/api/views.py
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.models import Document


class DocumentHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Document.history.model
        fields = [
            "history_id",
            "history_date",
            "history_type",
            "history_change_reason",
            "history_user_id",
            "title",
            "body",
        ]


class DocumentViewSet(viewsets.ModelViewSet):
    queryset = Document.objects.all()
    serializer_class = DocumentSerializer

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        document = self.get_object()
        history = document.history.all()
        serializer = DocumentHistorySerializer(history, many=True)
        return Response(serializer.data)
```

### 10. Querying history

```python
# Latest snapshot before a point in time
snapshot = document.history.as_of(datetime(2025, 1, 1, 0, 0))

# All changes by a user
Document.history.filter(history_user=user)

# All creations in the last day
Document.history.filter(history_type="+", history_date__gte=timezone.now() - timedelta(days=1))

# Diff between two historical records
old = document.history.get(history_id=5)
new = document.history.get(history_id=10)
diff = new.diff_against(old)
```

### 11. Excluded fields

Fields that should not be versioned can be excluded per model:

```python
class CachedReport(BaseAuditableModel):
    data = models.JSONField()
    cached_at = models.DateTimeField(auto_now=True)

    history = HistoricalRecords(excluded_fields=["cached_at"])
```

## Migration strategy

1. Add `django-simple-history` to dependencies and install it.
2. Update `INSTALLED_APPS` and `MIDDLEWARE` in `base.py`.
3. Add `BaseAuditableModel` to `apps.core.models`.
4. For each model that needs history:
   - Change its base class from `BaseModel` to `BaseAuditableModel`.
   - Generate and commit migrations for both the concrete table changes (if any) and the new
     historical table.
5. Register models that need admin history with `SimpleHistoryAdmin`.
6. Add nested history API endpoints where required.

## Testing strategy

Add tests in `src/apps/core/tests/test_audit_history.py`:

```python
import pytest
from django.contrib.auth import get_user_model

from apps.core.models import Document

User = get_user_model()


@pytest.mark.django_db
def test_history_record_created_on_save():
    doc = Document.objects.create(title="Original")
    doc.title = "Updated"
    doc.save()

    assert Document.history.count() == 2
    latest = Document.history.latest()
    assert latest.title == "Updated"
    assert latest.history_type == "~"


@pytest.mark.django_db
def test_history_records_deleted_instance():
    doc = Document.objects.create(title="To delete")
    doc.delete()

    latest = Document.history.latest()
    assert latest.history_type == "-"


@pytest.mark.django_db
def test_history_user_set_via_middleware(rf, admin_user):
    request = rf.post("/")
    request.user = admin_user

    from simple_history.middleware import HistoryRequestMiddleware
    middleware = HistoryRequestMiddleware(get_response=lambda r: r)
    middleware.process_request(request)

    doc = Document.objects.create(title="By user")
    latest = doc.history.latest()
    assert latest.history_user == admin_user
```

## Affected files

- `pyproject.toml`
- `src/config/settings/base.py`
- `src/apps/core/models.py`
- `src/apps/core/admin.py`
- `src/apps/<app>/models.py` (for each model opting into history)
- `src/apps/<app>/migrations/` (auto-generated historical tables)
- `src/apps/api/views.py` (for history endpoints)
- `src/apps/core/tests/test_audit_history.py` (new)

## Open questions

1. Should all existing models that inherit from `BaseModel` be migrated to `BaseAuditableModel`,
   or should adoption be model-by-model?
2. Should the nested history endpoint be added to a shared `BaseAuditableViewSet` mixin rather than
   implemented per model?
3. Should `history_change_reason` be required for programmatic/system updates?
4. Do we need to retain history rows indefinitely, or should we add a retention policy/cleanup job?

## References

- [django-simple-history documentation](https://django-simple-history.readthedocs.io/)
- ADR 0002 — Audit Attributes (`created_by` and `updated_by` in BaseModel)