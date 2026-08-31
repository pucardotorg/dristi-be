# Audit Attributes Specification: `created_by` and `updated_by` in BaseModel

## Status
Proposed

## 1. Goal

Track the user who created and last updated every record in a model hierarchy, without requiring every subclass to redefine these fields. The fields must:

- Support records created by authenticated API users.
- Support records created by system processes, background tasks (Dramatiq), or data migrations where no user context exists.
- Avoid Django reverse-relation naming conflicts when multiple models inherit from the same base model.
- Be easy to serialize in API responses.

## 2. Field Definition

Add two nullable foreign keys to the abstract base model:

```python
from django.conf import settings
from django.db import models


class BaseModel(models.Model):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        default=None,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_created_by",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        default=None,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_updated_by",
    )

    class Meta:
        abstract = True
```

### 2.1 Why nullable?

- Allows records to be created by system processes, Dramatiq actors, management commands, migrations, or imports.
- Avoids the need for a dummy user or fake attribution.
- Makes the audit trail honest: `NULL` means "no known user."

### 2.2 Why `on_delete=models.SET_NULL`?

- If the creating/updating user is deleted, the record remains.
- The audit field is cleared rather than cascading the deletion or blocking it.

### 2.3 Why dynamic `related_name`?

Because every concrete subclass will have two foreign keys to the same user model. Without unique `related_name` values, Django raises:

```
Reverse accessor for 'Model.created_by' clashes with reverse accessor for 'Model.updated_by'.
```

Using `%(app_label)s_%(class)s_` produces unique reverse accessors per concrete model (e.g., `users_user_created_by`, `core_document_updated_by`).

### 2.4 Why `settings.AUTH_USER_MODEL`?

This avoids a hard import of the user model and follows Django’s recommendation for reusable code and swappable user models.

## 3. Migrations

Because `BaseModel` is abstract, adding these fields will require a migration for every concrete model that inherits from it. The migration should be generated with:

```bash
python manage.py makemigrations
```

## 4. Automatic Population

### 4.1 In DRF view mixins

The base API mixins should set these fields automatically:

```python
from django.db import transaction


class AuditCreateMixin:
    def perform_create(self, serializer):
        serializer.save(
            created_by=self.request.user,
            updated_by=self.request.user,
        )


class AuditUpdateMixin:
    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)
```

### 4.2 Rules

| Operation | `created_by` | `updated_by` |
|-----------|--------------|--------------|
| Create | Set to current user | Set to current user |
| Update | Unchanged | Set to current user |
| System/batch | `NULL` or a dedicated system user | `NULL` or a dedicated system user |

## 5. System / Background Process Handling

When no request user exists (Dramatiq tasks, management commands, imports), leave the fields as `NULL` or use a dedicated system user.

### 5.1 Use a dedicated system user

Use when you need to distinguish system actions from unknown/null origins.

```python
from django.contrib.auth import get_user_model

User = get_user_model()

system_user, _ = User.objects.get_or_create(
    username="system",
    email="system@dristi.local",
)
record = MyModel.objects.create(
    name="Batch import item",
    created_by=system_user,
    updated_by=system_user,
)
```

## 6. Serialization

Provide a reusable helper on the base serializer/resource class:

```python
from rest_framework import serializers


class AuditUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = None  # set dynamically or use a concrete user serializer
        fields = ["id", "email", "username"]


class BaseSerializer(serializers.ModelSerializer):
    created_by = AuditUserSerializer(read_only=True, allow_null=True)
    updated_by = AuditUserSerializer(read_only=True, allow_null=True)
```

Or, if serialization must be done in a helper method:

```python
def serialize_audit_users(mapping, obj):
    if obj.created_by_id:
        mapping["created_by"] = {"id": obj.created_by_id}
    if obj.updated_by_id:
        mapping["updated_by"] = {"id": obj.updated_by_id}
```

## 7. Best Practices

1. **Always use the dynamic `related_name` pattern** when an abstract base model has multiple FKs to the same target model.
2. **Do not make these fields non-nullable** unless every record is guaranteed to be created by an authenticated user.
3. **Set `updated_by` on every save that changes user-visible data**, including custom actions that bypass the standard view mixins.
4. **Do not use `created_by` for authorization** unless you also enforce that it is never `NULL`.
5. **Foreign keys are indexed by default** (`db_index=True`), which is the Django default.
6. **Document the meaning of `NULL` or `SYSTEM`** in API documentation and client contracts.
