# 0006 — Active-Flag Mixin

## Status

Proposed

## Context

Several models in Dristi need a standard way to be soft-disabled without being deleted. Examples include administrative locations, lookup tables, and reference data. Rather than adding an `is_active` flag to every model individually, we want a single reusable abstract mixin.

This spec intentionally does **not** modify `BaseModel`, because `is_active` is not meaningful for every table (e.g. audit logs, transition logs). Keeping it opt-in avoids migrations and semantic overload on models that do not need lifecycle disabling.

## Goals

- Provide a reusable abstract mixin `BaseActivatableModel` that adds an `is_active` Boolean field.
- Provide a custom queryset/manager with explicit `active()` and `inactive()` helpers.
- Leave default querying unchanged so existing code is not surprised by hidden filters.
- Let models opt in by inheriting from the mixin alongside `BaseModel` or `BaseExtendableModel`.

## Non-goals

- Soft-delete semantics (cascading deactivation, restore workflows, tombstone records).
- Replacing or modifying `BaseModel`.
- Automatically filtering inactive rows from every query.

## Proposed changes

### 1. `BaseActivatableModel` abstract mixin

Location: `apps.core.models`

```python
class ActivatableQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)


class BaseActivatableModel(models.Model):
    is_active = models.BooleanField(default=True)

    objects = ActivatableQuerySet.as_manager()

    class Meta:
        abstract = True
```

Behaviour:

- New rows default to `is_active=True`.
- `Model.objects.active()` returns only rows with `is_active=True`.
- `Model.objects.inactive()` returns only rows with `is_active=False`.
- `Model.objects.all()` and all other queryset operations remain unchanged — inactive rows are included by default.

### 2. Usage with `BaseModel` / `BaseExtendableModel`

Models opt in by adding `BaseActivatableModel` to their inheritance list.

```python
class SomeReferenceTable(BaseModel, BaseActivatableModel):
    name = models.CharField(max_length=255)
    ...
```

```python
class SomeExtendableReference(BaseExtendableModel, BaseActivatableModel):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    ...
```

Order of mixins:

- Django requires exactly one concrete `models.Model` base in the hierarchy. Because `BaseModel` and `BaseExtendableModel` already inherit from `models.Model` (abstract), and `BaseActivatableModel` is also abstract, the concrete model must inherit from one of the project base models first.
- Put the project base model (`BaseModel` or `BaseExtendableModel`) before `BaseActivatableModel` if there is any field overlap; otherwise either order is acceptable.

### 3. Manager considerations

If a model already defines a custom manager (e.g. `ActiveRoleQuerySet`), compose the activatable queryset into the existing one instead of replacing it:

```python
class MyCustomQuerySet(ActivatableQuerySet, ExistingQuerySet):
    pass

class MyModel(BaseModel, BaseActivatableModel):
    objects = MyCustomQuerySet.as_manager()
    ...
```

This preserves both `active()` / `inactive()` and the model-specific queryset methods.

### 4. Admin interface guidance

For models using the mixin, the admin should:

- List display: include `is_active`.
- List filter: include `is_active`.
- Default changelist should **not** hide inactive rows unless the feature explicitly calls for it.

### 5. API filtering guidance

For models using the mixin, list APIs may optionally expose an `is_active` query parameter:

```http
GET /some-reference/?is_active=true
GET /some-reference/?is_active=false
```

This is not enforced by the mixin itself; each app’s viewset/serializer adds the filter as needed.

## Affected files

- `src/apps/core/models.py`
- `src/apps/core/tests/test_activatable_model.py`

## Open questions

1. Should `BaseActivatableModel` provide a `deactivate()` / `activate()` helper method on the instance, or is assigning `is_active` directly sufficient?
2. Should the mixin include an `activated_at` / `deactivated_at` timestamp pair for audit purposes?
3. Should there be a management command to bulk deactivate stale reference data?

## Out of scope

- Replacing or modifying `BaseModel`.
- Global default manager that excludes inactive rows.
- Soft-delete with related-object cascading.
- Restoration/reactivation workflows beyond setting `is_active=True`.
