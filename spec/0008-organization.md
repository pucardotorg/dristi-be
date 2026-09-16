# 0008 — Organization Module

## Status

Proposed

## Context

Dristi needs an organization hierarchy to represent judicial bodies (for example, Supreme Court, High Court, District Court), model parent-child administrative structure, and map each organization to one or more jurisdictions.

The location hierarchy introduced in `0007-location.md` already models geography. Organizations should reuse that module for jurisdiction mapping instead of duplicating location data.

## Goals

- Introduce an `Organization` model with hierarchical parent-child structure.
- Enforce globally unique organization `code` values in uppercase snake_case.
- Support fixed organization types relevant to courts.
- Associate each organization with one or more `Location` rows as jurisdiction.
- Expose read-only APIs (GET only), aligned with the location API style.

## Non-goals

- Write APIs (create/update/delete) for organizations.
- Role/user membership in organizations.
- Case assignment rules by organization.
- Historical versioning of organizational boundaries.

## Proposed changes

### 1. App layout

Create a dedicated Django app for organizations:

```
src/apps/organizations/
├── __init__.py
├── apps.py
├── models.py          # Organization
├── admin.py           # register Organization
├── serializers.py     # Organization serializers
├── views.py           # read-only viewset
├── urls.py            # route registration
└── tests/
    └── test_organization.py
```

`Organization` inherits from `BaseModel`, `BaseExtendableModel`, and `BaseActivatableModel`.

Register `apps.organizations` in `src/config/settings/base.py` under `INSTALLED_APPS` and mount URLs under `/api/v1/organizations/` in `src/config/urls.py`.

### 2. `OrganizationType` choices

| Value | DB value | Label |
|-------|----------|-------|
| `SUPREME_COURT` | `supreme_court` | Supreme Court |
| `HIGH_COURT` | `high_court` | High Court |
| `DISTRICT_COURT` | `district_court` | District Court |
| `SESSION_COURT` | `session_court` | Session Court |
| `MAGISTRATE_COURT` | `magistrate_court` | Magistrate Court |

### 3. `Organization` model

Organization: `apps.organizations.models`

Inherits from `BaseModel`, `BaseExtendableModel`, and `BaseActivatableModel`.

| Field | Type | Notes |
|-------|------|-------|
| `code` | `CharField(max_length=50, unique=True)` | Stable unique machine identifier, uppercase snake_case only. |
| `organization_type` | `CharField(max_length=50)` | One of the organization type choices above. |
| `name` | `CharField(max_length=255)` | Full display name. |
| `short_name` | `CharField(max_length=100, blank=True)` | Optional short display name. |
| `description` | `TextField(blank=True)` | Optional descriptive text. |
| `parent` | `ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")` | Null means top-level organization. Child has one parent; parent has many children. |
| `jurisdictions` | `ManyToManyField("locations.Location", related_name="organizations")` | One organization maps to one or more locations from `0007-location.md`. |
| `is_active` | `BooleanField(default=True)` | Inherited from `BaseActivatableModel`. |

Constraints:

- `code` is unique across all organizations.
- A child organization has exactly one parent; top-level organization has `parent = null`.
- A parent can have multiple children.
- `parent` is protected from deletion while children exist.
- Jurisdiction relationship is many-to-many with `Location`.

Validation (`clean()` / `save()`):

- `code` must match `^[A-Z0-9_]+$` (uppercase snake_case).
- `organization_type` must be one of the supported choices.
- `self.parent != self`.
- Prevent circular parent chains (`self` cannot appear in its ancestor path).
- Jurisdiction set should contain at least one location for active organizations (validated at serializer/admin level; DB-level min-count constraint is not available for Django M2M).

### 4. Hierarchy semantics

- If `parent_id` is null, the organization is a parent/root organization.
- If `parent_id` is set, the organization is a child of that parent.
- A parent organization can have multiple child organizations.
- A child organization can have only one parent organization.

### 5. Model methods

| Method | Purpose |
|--------|---------|
| `get_ancestors()` | Return ordered list from root to immediate parent. |
| `get_descendants()` | Return all nested children recursively. |
| `is_root()` | `True` when `parent is None`. |
| `get_full_name()` | Concatenate ancestors and name, e.g. `"India Supreme Court / Patna Bench"`. |

### 6. Admin interface

Register `Organization` in `apps.organizations.admin` with:

- List display: `code`, `name`, `short_name`, `organization_type`, `parent`, `is_active`.
- List filters: `organization_type`, `is_active`.
- Search fields: `code`, `name`, `short_name`.
- Filter horizontal / autocomplete for `jurisdictions`.
- Read-only: audit fields from `BaseModel`.

Deletion behavior:

- Because `parent` uses `PROTECT`, deleting a parent organization with children raises `ProtectedError`.

### 7. API surface (read-only for v1)

Base path: `/api/v1/organizations/`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/organizations/` | List organizations. Supports filtering by `organization_type`, `parent_id`, `parent_code`, `jurisdiction_id`, `jurisdiction_code`, and `is_active`. |
| GET | `/organizations/{id}/` | Retrieve an organization by `id`. |
| GET | `/organizations/code/{code}/` | Retrieve an organization by unique `code`. |
| GET | `/organizations/{id}/children/` | List direct children by organization `id`. |
| GET | `/organizations/code/{code}/children/` | List direct children by organization `code`. |
| GET | `/organizations/{id}/ancestors/` | List ancestor chain from root to immediate parent by `id`. |
| GET | `/organizations/code/{code}/ancestors/` | List ancestor chain from root to immediate parent by `code`. |
| GET | `/organizations/{id}/jurisdictions/` | List jurisdiction locations for an organization by `id`. |
| GET | `/organizations/code/{code}/jurisdictions/` | List jurisdiction locations for an organization by `code`. |

No write endpoints are included in v1. Organizations are managed via Django admin and data migrations.

Query examples:

- `GET /organizations/?organization_type=high_court`
- `GET /organizations/?parent_code=SUPREME_COURT_INDIA`
- `GET /organizations/?jurisdiction_code=BR`
- `GET /organizations/?is_active=false`

Filter validation:

- `parent_id` and `parent_code` are mutually exclusive.
- `jurisdiction_id` and `jurisdiction_code` are mutually exclusive.

### 8. Example data

| code | organization_type | name | short_name | parent code | jurisdictions |
|------|-------------------|------|------------|-------------|---------------|
| `SUPREME_COURT_INDIA` | `supreme_court` | Supreme Court of India | SCI | — | `IN` |
| `PATNA_HIGH_COURT` | `high_court` | High Court of Judicature at Patna | Patna HC | `SUPREME_COURT_INDIA` | `BR` |
| `PATNA_DISTRICT_COURT` | `district_court` | District Court Patna | Patna DC | `PATNA_HIGH_COURT` | `PATNA` |

## Affected files

- `src/config/settings/base.py`
- `src/config/urls.py`
- `src/apps/organizations/__init__.py`
- `src/apps/organizations/apps.py`
- `src/apps/organizations/models.py`
- `src/apps/organizations/admin.py`
- `src/apps/organizations/serializers.py`
- `src/apps/organizations/views.py`
- `src/apps/organizations/urls.py`
- `src/apps/organizations/tests/test_organization.py`

## Open questions

- Should any organization types be restricted to specific parent types (for example, District Court must belong under a High Court)?
- Should inactive locations be allowed in jurisdiction mappings for active organizations?

## Out of scope

- User membership/roles inside organizations.
- Organization-specific workflow configuration.
- Temporal jurisdiction history.

## Related specs

- `0001-additional-attributes.md` — defines `BaseExtendableModel`.
- `0002-audit-fields-base-model.md` — defines `BaseModel`.
- `0006-active-flag-model.md` — defines `BaseActivatableModel`.
- `0007-location.md` — location hierarchy used by organization jurisdictions.
