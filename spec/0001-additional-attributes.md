# 0001 — Additional Attributes

## Status
Proposed

## Context
Several domain models in Dristi may need to store extra, model-specific fields without requiring a schema migration for every new attribute. We want a small, opt-in extension layer that lets projects declare additional columns dynamically while still keeping data typed and validated.

## Goals
- Provide a reusable abstract model `BaseExtendableModel` that adds a single `additional_attributes` JSON column.
- Allow teams to declare allowed additional columns in a central `AdditionalAttribute` table.
- Enforce type, nullability, and default-value rules when a model instance is saved.
- Keep `BaseModel` unchanged so existing models are unaffected unless they explicitly opt in.

## Non-goals
- Generic JSON-schema validation for arbitrary keys.
- Runtime migration generation (no `ALTER TABLE`).
- Supporting nested objects inside `additional_attributes`; values should be scalars.

## Proposed changes

### 1. `BaseExtendableModel` abstract model

Location: `apps.core.models`

Inherits from `models.Model` and adds a single `additional_attributes` JSON column. Models that also need the UUID primary key and timestamp fields from `BaseModel` must inherit from `BaseModel` explicitly in addition to `BaseExtendableModel`.

| Field | Type | Notes |
|-------|------|-------|
| `additional_attributes` | `JSONField(default=dict)` | Stores `{name: value}` pairs as plain JSON. |

```python
class BaseExtendableModel(models.Model):
    additional_attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True
```

Behavior:
- On `save()` (or via a dedicated clean method), validate every key present in `additional_attributes` against matching rows in `AdditionalAttribute`.
- Reject unknown keys unless the project explicitly enables a permissive mode (out of scope for the initial implementation).
- Coerce values to the declared type if possible; raise `ValidationError` if coercion fails.
- Apply default values from the metadata row when a nullable column is missing.
- If a non-nullable column is missing and has no default, raise `ValidationError`.

### 2. `AdditionalAttribute` model

Location: `apps.core.models`

Stores metadata describing which extra attributes are allowed on which models.

| Field | Type | Notes |
|-------|------|-------|
| `content_type` | `ForeignKey(ContentType, on_delete=models.CASCADE)` | Django-standard reference to the model this attribute belongs to. |
| `name` | `CharField(max_length=255)` | Name of the additional attribute. Must be snake_case. Validated with a regex. |
| `data_type` | `CharField(max_length=50)` | One of: `integer`, `float`, `number`, `character`, `boolean`, `datetime`, `date`, `json`. Stored lowercase. |
| `is_nullable` | `BooleanField(default=True)` | Whether the attribute may be omitted or set to `null`. |
| `default_value` | `JSONField(default=None, null=True, blank=True)` | Default value applied when the attribute is missing. Must be compatible with `data_type`. |

Constraints:
- Unique together: (`content_type`, `name`).
- Validation in `AdditionalAttribute.clean()`:
  - Ensure `name` matches `^[a-z][a-z0-9_]*$` (snake_case, starts with lowercase letter).
  - Ensure `default_value` matches `data_type`.
  - Ensure non-nullable rows have a non-null default.

`ContentType` comes from Django’s `django.contrib.contenttypes` framework. `INSTALLED_APPS` already includes `django.contrib.contenttypes` by default in a Django project, but the spec assumes it is present.

### 3. Type coercion rules

| Declared `data_type` | Python target type | Notes |
|---------------------|-------------------|-------|
| `integer` | `int` | `int(value)`; rejects non-integer floats. |
| `float` | `float` | `float(value)`. |
| `number` | `int` if value is integral, else `float` | Convenience type for numeric values. |
| `character` | `str` | `str(value)`. |
| `boolean` | `bool` | Accepts booleans; rejects strings except `"true"`/`"false"` (case-insensitive). |
| `datetime` | `datetime.datetime` (ISO string in JSON) | Stored as ISO string; validated on save. |
| `date` | `datetime.date` (ISO string in JSON) | Stored as ISO string; validated on save. |
| `json` | any JSON-serializable value | No coercion; must be JSON-serializable. |

### 4. Validation flow

When an instance of a concrete `BaseExtendableModel` subclass is saved:

1. Load all `AdditionalAttribute` rows for the instance’s `content_type`.
2. For each declared attribute:
   - If the key is absent:
     - If a default exists, set it.
     - Else if `is_nullable=False`, raise `ValidationError`.
   - If the key is present and value is `null`:
     - If `is_nullable=False`, raise `ValidationError`.
   - If the key is present and value is not `null`:
     - Coerce to declared type; raise `ValidationError` on failure.
3. Remove unknown keys or raise `ValidationError` (TBD during implementation; raising is safer).

### 5. Usage example

```python
# apps/users/models.py
class User(BaseModel, BaseExtendableModel):
    email = models.EmailField(unique=True)


# AdditionalAttribute rows (created via admin or migration)
from django.contrib.contenttypes.models import ContentType

user_ct = ContentType.objects.get(app_label="users", model="user")

AdditionalAttribute.objects.create(
    content_type=user_ct,
    name="age",
    data_type="integer",
    is_nullable=True,
)
AdditionalAttribute.objects.create(
    content_type=user_ct,
    name="department",
    data_type="character",
    is_nullable=False,
    default_value="Engineering",
)

# Runtime usage
user = User.objects.create(
    email="alice@example.com",
    additional_attributes={"age": 30},
)
# After validation/cleaning, additional_attributes becomes:
# {"age": 30, "department": "Engineering"}
```

## Open questions
1. Should unknown keys be silently stripped, logged, or rejected?
2. Should validation happen only in `clean()` or also override `save()` to call `full_clean()`?
3. Do we need an admin interface for `AdditionalAttribute` in the initial implementation?

## Affected files
- `src/apps/core/models.py`
- `src/apps/core/admin.py` (optional)
- `src/apps/core/tests/test_extendable_model.py`

## Out of scope
- UI for managing additional attributes.
- Migrations for concrete models (each concrete model will receive its own migration for the JSON field when it opts in).
- Querying/filtering by additional attribute values at the database level.
