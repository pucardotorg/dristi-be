# 0007 — Location Module

## Status

Proposed

## Context

Dristi needs a hierarchical location reference so that cases, courts, users, and other domain entities can be tagged to a country, state, district, or any future administrative level. Locations must be configurable at the data level, reusable across modules, and extensible with additional attributes without schema changes.

## Goals

- Provide a single `Location` model that represents an administrative area in a self-referential hierarchy.
- Support top-level locations (country) and nested locations (state under country, district under state).
- Enforce uniqueness of location codes and single-parent constraints.
- Allow each location to store extra typed fields via `BaseExtendableModel`.

## Non-goals

- Geographic polygons, coordinates, or GIS features.
- Multi-tenancy or per-organization location scoping.
- Location search, autocomplete, or full-text indexing.

## Proposed changes

### 1. App layout

Create a dedicated Django app for locations:

```
src/apps/locations/
├── __init__.py
├── apps.py
├── models.py          # Location
├── admin.py           # register Location
├── serializers.py     # Location serializers
├── views.py           # read-only viewset
├── urls.py            # route registration
└── tests/
    └── test_location.py
```

`Location` inherits from `BaseModel`, `BaseExtendableModel`, and `BaseActivatableModel` (see `0006-active-flag-model.md`). Register `apps.locations` in `src/config/settings/base.py` under `INSTALLED_APPS` and mount its URLs under `/api/v1/locations/` in `src/config/urls.py`.

### 2. `LocationType` choices

| Value | DB value | Label |
|-------|----------|-------|
| `COUNTRY` | `country` | Country |
| `STATE` | `state` | State |
| `DISTRICT` | `district` | District |
| `PINCODE` | `pincode` | Pincode |

The list is intentionally small for v1. Additional choices (e.g. `tehsil`, `block`, `village`) can be added without breaking existing rows.

### 3. `Location` model

Location: `apps.locations.models`

Inherits from `BaseModel`, `BaseExtendableModel`, and `BaseActivatableModel`.

| Field | Type | Notes |
|-------|------|-------|
| `code` | `CharField(max_length=50, unique=True)` | Stable, unique machine identifier. Not null. Enforced uppercase snake_case. |
| `name` | `CharField(max_length=255)` | Full display name. |
| `short_name` | `CharField(max_length=100, blank=True)` | Optional short display name. |
| `location_type` | `CharField(max_length=50)` | One of `country`, `state`, `district`, `pincode`. |
| `parent` | `ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")` | Null for top-level locations. Protected from deletion while children exist. |
| `is_active` | `BooleanField(default=True)` | Inherited from `BaseActivatableModel`. Soft-disable flag. |

Constraints:

- `code` is unique across all locations.
- A location may have zero or one parent.
- A parent location may have many children via the `children` related name.

Validation (`clean()` / `save()`):

- `code` must match `^[A-Z0-9_]+$` (uppercase snake_case). Values are rejected if they do not match; no silent normalisation.
- `location_type` must be one of the supported choices.
- Prevent a location from being its own parent: `self.parent != self`.
- Prevent circular parent chains: an ancestor of `self.parent` must not be `self`.

### 4. Model methods

| Method | Purpose |
|--------|---------|
| `get_ancestors()` | Return ordered list from root to immediate parent. |
| `get_descendants()` | Return all nested children recursively. |
| `is_root()` | `True` when `parent is None`. |
| `get_full_name()` | Concatenate ancestors and name, e.g. `"India / Bihar / Patna"`. |

### 5. Admin interface

Register `Location` in `apps.locations.admin` with:

- List display: `code`, `name`, `short_name`, `location_type`, `parent`, `is_active`.
- List filters: `location_type`, `is_active`.
- Search fields: `code`, `name`, `short_name`.
- Read-only: audit fields from `BaseModel`.

Deletion behaviour: because `parent` uses `PROTECT`, attempting to delete a location that has children will raise `ProtectedError`. The admin should surface this clearly to prevent accidental deletion of parent locations.

### 6. API surface (read-only for v1)

Base path: `/api/v1/locations/`

### API authentication

The `/api/v1/locations/` endpoints are currently publicly accessible
and do not require authentication.

Authentication will be added in a future change.
Until then, all read-only location endpoints described in this
specification are accessible without authentication.

This is intentional for v1 and should not be interpreted as the
final security model for the API.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/locations/` | List locations. Supports filtering by `location_type`, `parent_id`, and `parent_code`. |
| GET | `/locations/{id}/` | Retrieve a location by its `id`. |
| GET | `/locations/code/{code}/` | Retrieve a location by its unique `code`. |
| GET | `/locations/{id}/children/` | List direct children of a location identified by `id`. |
| GET | `/locations/code/{code}/children/` | List direct children of a location identified by `code`. |
| GET | `/locations/{id}/ancestors/` | List ancestor chain from root to immediate parent, identified by `id`. |
| GET | `/locations/code/{code}/ancestors/` | List ancestor chain from root to immediate parent, identified by `code`. |

No write endpoints are included in v1. Locations are managed through the Django admin or data migrations.

Query examples:

- `GET /locations/?location_type=state` — list all states.
- `GET /locations/?parent_code=IN` — list all direct children of the location whose code is `IN`.
- `GET /locations/?parent_id=<state-uuid>&location_type=district` — list all districts under a given state.
- `GET /locations/?is_active=false` — list disabled locations.

`parent_id` and `parent_code` are explicit, mutually-exclusive filters. Validation rejects requests that supply both. `is_active` filtering is provided because `Location` uses `BaseActivatableModel`.

### 7. Pincodes

Postal pincodes are `pincode` locations whose parent is a district, so an
address form can pre-fill district and state without calling a third-party
API (spec 0020):

```
GET /api/v1/locations/code/PIN_560001/ancestors/?is_active=true
→ {"data": [India (country), Karnataka (state), Bengaluru Urban (district)], "meta": {...}}
```

The client takes `district` and `state` from the entries whose
`location_type` is `district` and `state`. `is_active=true` makes the call
`404` unless the pincode and every location above it are active, so
deactivating a wrong pincode or district stops it pre-filling. On both
`ancestors` routes, `is_active=false` finds only an inactive location, and any
other value is a `400`, so a typo never skips the check. A `404` means
"no pre-fill": the user enters district and state by hand.

| Field | Value |
|-------|-------|
| `code` | `PIN_<pincode>`, e.g. `PIN_560001` |
| `name`, `short_name` | The pincode, e.g. `560001` |
| `parent` | The district. `clean()` rejects any other parent, any location placed under a pincode, and a type change on a district that holds pincodes |

The admin picks a location's parent with a search box, and an organization's
jurisdictions never list pincodes, since the table holds tens of thousands of
them.

Pincodes, and the states and districts above them, are seeded from TOML with
the `seed` command (spec 0025). India Post's *All India Pincode Directory* CSV
is converted to TOML out-of-band — the converter (which does the de-duplication
and name matching) and the generated `states.toml`, `districts.toml` and
`pincodes.toml` live in the `dristi-be-experiments` repo (issue #196):

```bash
python manage.py seed states.toml districts.toml pincodes.toml
```

Loading is part of setting up an environment, done once; the repository ships
no location data. The files load in that order (a district's `parent` is a
state code, a pincode's `parent` is a district code), each row is matched by
its `code` and only missing rows are inserted, so re-running is safe. Seeding
is insert-only: existing rows are never changed, and nothing is deleted. The
`Location` model's `clean()` still enforces the hierarchy — a pincode's parent
must be a district — so a malformed row is rejected rather than stored.

## Example data

A location `code` may include the parent code for readability (e.g. `IN_BR_PATNA`) or be independent (e.g. `PATNA`). The system does not enforce either convention.

| code | name | short_name | location_type | parent code |
|------|------|------------|---------------|-------------|
| `IN` | India | IN | country | — |
| `BR` | Bihar | BR | state | IN |
| `PATNA` | Patna | Patna | district | BR |

## Affected files

- `src/config/settings/base.py`
- `src/config/urls.py`
- `src/apps/locations/__init__.py`
- `src/apps/locations/apps.py`
- `src/apps/locations/models.py`
- `src/apps/locations/admin.py`
- `src/apps/locations/serializers.py`
- `src/apps/locations/views.py`
- `src/apps/locations/urls.py`
- `src/apps/locations/tests/test_location.py`
- `src/apps/locations/migrations/0003_location_type_pincode.py`
- `src/apps/locations/admin.py`, `src/apps/organizations/admin.py`

Pincodes were originally loaded by a dedicated `import_pincodes` command; it was
removed in favour of the generic `seed` command (spec 0025, issue #196).

## Open questions

_None — the `is_active` flag is handled by `0006-active-flag-model.md`._

## Out of scope

- GIS/geometry fields.
- Multi-language location names.
- Location import utilities from government gazetteers, other than the pincode import (section 7).
- Address formatting.
- A persisted `level`/depth column; depth can be derived from ancestors when needed and a denormalised column can be added later if performance requires it.

## Related specs

- `0006-active-flag-model.md` — defines `BaseActivatableModel` used by `Location`.

## TODO

- Add authentication to the `/api/v1/locations/` endpoints in a future change.
- A generic base serialization class is being built and will be implemented in a future change.