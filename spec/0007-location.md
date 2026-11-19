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
| `BANK` | `bank` | Bank |
| `POLICE_STATION` | `police_station` | Police station |

The list is intentionally small for v1. Additional choices (e.g. `tehsil`, `block`, `village`) can be added without breaking existing rows.

### 3. `Location` model

Location: `apps.locations.models`

Inherits from `BaseModel`, `BaseExtendableModel`, and `BaseActivatableModel`.

| Field | Type | Notes |
|-------|------|-------|
| `code` | `CharField(max_length=50, unique=True)` | Stable, unique machine identifier. Not null. Enforced uppercase snake_case. |
| `name` | `CharField(max_length=255)` | Full display name. |
| `short_name` | `CharField(max_length=100, blank=True)` | Optional short display name. |
| `location_type` | `CharField(max_length=50)` | One of `country`, `state`, `district`, `pincode`, `bank`, `police_station`. |
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
| GET | `/locations/code/{code}/` | Retrieve a location by its unique `code`. Optional `location_type` and `is_active` make it `404` unless the location matches (see section 8). |
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
- `GET /locations/?parent_code=IN_KERALA_THRISSUR&location_type=police_station&is_active=true&page_size=100` — a district's police stations for a dropdown (section 9).

`parent_id` and `parent_code` are explicit, mutually-exclusive filters. Validation rejects requests that supply both. `is_active` filtering is provided because `Location` uses `BaseActivatableModel`. An empty filter value (for example `?is_active=`) is treated as not sent.

Lists are paginated, 20 per page by default. `page_size` asks for up to 100 per page, so a dropdown can load all of a district's police stations in one call (issue #250).

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
`ancestors` routes, `is_active=false` finds only an inactive location, an
empty value (`?is_active=`) is treated as not sent, and any other value is a
`400`, so a typo never skips the check. A `404` means
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

### 8. Banks

A bank branch is a `bank` location keyed by its IFSC, so the e-filing form can
fill a cheque's bank name and branch from the IFSC the user types (issue #249):

```
GET /api/v1/locations/code/AUBL0002670/?location_type=bank&is_active=true
→ {"code": "AUBL0002670", "name": "AU Small Finance Bank - M G ROAD KOCHI",
   "short_name": "AUBL0002670", "location_type": "bank",
   "parent_code": "IN_KERALA_ERNAKULAM",
   "additional_attributes": {"address": "BUILDING DOOR NOS. 62/5202 ..., MG ROAD, KOCHI, KERALA"}, ...}
```

The client uppercases the IFSC before the call. `location_type=bank` and
`is_active=true` make the call `404` for a code that is not a bank or for a
closed branch; a `404` means "no pre-fill" and the user enters the bank and
branch by hand. Filing never checks that an IFSC exists here, since new
branches open between data releases.

| Field | Value |
|-------|-------|
| `code` | The IFSC, e.g. `AUBL0002670`. `clean()` rejects a bank whose code is not an IFSC (`^[A-Z]{4}0[A-Z0-9]{6}$`) |
| `name` | `<BANK> - <BRANCH>` |
| `short_name` | The IFSC |
| `parent` | The branch's district. `clean()` rejects any other parent, any location placed under a bank, and a type change on a district holding banks |
| `additional_attributes.address` | The branch address. Optional; `clean()` does not require it |

`address` is an additional attribute on `Location`, defined by the seed file
`data/seed/core/additional_attributes.toml` (not a migration), which must be
loaded before any bank rows that carry an address. It is nullable, so once it is
defined every other location carries `"address": null`.

Like pincodes, banks never appear in an organization's jurisdictions, and a
district's `children` list them alongside its pincodes (filter by
`location_type`).

Only **Kerala** branches are seeded for now. They come from
[razorpay/ifsc](https://github.com/razorpay/ifsc) (RBI's list), converted to
TOML out-of-band (`ifsc_to_toml.py`, kept with the pincode converter in the
`dristi-be-experiments` repo). Razorpay's `DISTRICT` column is free text that
often does not match our district names, so the converter places each branch
by the first step that works:

1. the pincode in the address → its district (India Post directory);
2. `DISTRICT`, then `CITY`, equals a district name or a known old name or
   spelling (Trivandrum, Trichur, Calicut, Cochin, Alleppey, Quilon, …);
3. a district name appears inside `DISTRICT`/`CITY`, then inside the address;
4. `DISTRICT` or `CITY` is a known town (Cherthala → Alappuzha, Thiruvalla →
   Pathanamthitta, …).

On Razorpay v2.0.62 this places 8,964 of 9,029 Kerala branches (99.3%; 74%
by pincode). The other 65 are left out — about half are branches elsewhere
mislabelled as Kerala — so their IFSC lookup is a `404` and the user enters
the details by hand, as for any IFSC outside Kerala. The converter's report
lists every left-out branch and every text-matched one for review.

```bash
python manage.py seed data/seed/core/                 # defines `address`
python manage.py seed states.toml districts.toml      # IN_KERALA and its districts
python manage.py seed banks_kerala.toml               # about 10 seconds
```

### 9. Police stations

A police station is a `police_station` location, so the address form can
suggest the stations for the address's district or pincode (issue #250). The
API needs nothing new; it is public for reading like every location route.

**By district** — list the district's active stations:

```
GET /api/v1/locations/?parent_code=IN_KERALA_THRISSUR&location_type=police_station&is_active=true&page_size=100
→ {"count": 41, "results": [{"code": "15996001", "name": "THRISSUR EAST",
   "location_type": "police_station", "parent_code": "IN_KERALA_THRISSUR",
   "additional_attributes": {"address": null, "police_district": "THRISSUR CITY"}, ...}, ...]}
```

**By pincode** — the form already reads the pincode's district from its
ancestors to pre-fill the address (section 7); it then lists that district's
stations as above:

```
GET /api/v1/locations/code/680001/ancestors/?is_active=true   → [..., {"code": "IN_KERALA_THRISSUR", ...}]
```

The station data has no pincodes, so a pincode suggests every station in its
district. The largest districts (Ernakulam, Thiruvananthapuram) have 61
stations, so `page_size=100` loads any district in one call. The list is a
suggestion only: the address keeps the chosen station as text
(`Address.police_station`), and filing never checks it against this list.

| Field | Value |
|-------|-------|
| `code` | The station's 8-digit code from V1's MDMS `PoliceStation` master, unchanged (e.g. `15996001`), so V1 data maps across. `clean()` rejects any other code |
| `name` | The station name, uppercase (e.g. `THRISSUR EAST`) |
| `short_name` | Blank |
| `parent` | The revenue district the station's police district lies in, or the state for a state-wide unit. `clean()` rejects any other parent, any location placed under a station, and a type change that would leave stations under something other than a district or a state |
| `additional_attributes.police_district` | The police district as MDMS names it (e.g. `THRISSUR CITY`) |

`police_district` is defined in `data/seed/core/additional_attributes.toml`,
alongside `address`; both are nullable, so every location carries both keys.

**Police districts.** Kerala Police splits five revenue districts into a city
and a rural police district. Each maps to its revenue district:

| Police district (MDMS) | Parent |
|------------------------|--------|
| `THIRUVANANTHAPURAM CITY`, `THIRUVANANTHAPURAM RURAL` | `IN_KERALA_THIRUVANANTHAPURAM` |
| `KOLLAM CITY`, `KOLLAM RURAL` | `IN_KERALA_KOLLAM` |
| `ERNAKULAM CITY`, `ERNAKULAM RURAL` | `IN_KERALA_ERNAKULAM` |
| `THRISSUR CITY`, `THRISSUR RURAL` | `IN_KERALA_THRISSUR` |
| `KOZHIKODE CITY`, `KOZHIKODE RURAL` | `IN_KERALA_KOZHIKODE` |
| `WYNAD` | `IN_KERALA_WAYANAD` |
| `KASARGODE` | `IN_KERALA_KASARAGOD` |
| `RAILWAY POLICE` (13), `C I D` (2) | `IN_KERALA` (state-wide) |
| any other | `IN_KERALA_<same name>` |

Railway police and CID stations serve the whole state, so they sit under the
state and do not appear in a district's suggestions. Police district
boundaries need not follow revenue district boundaries exactly, so an address
near a border may not see its station in the suggestions; the user can still
type any station.

Only **Kerala** is seeded: 517 stations in
`data/seed/kerala/police_stations.toml`, converted from V1's MDMS master.
Names are uppercased, and two railway station names are corrected
(`HIRUVANANTHAPURAM RAILWA` → `THIRUVANANTHAPURAM RAILWAY`,
`ERNAKUMAL RAILWAY` → `ERNAKULAM RAILWAY`). Non-territorial units in the
master (traffic, Vanitha, coastal, Special Mobile Squad, Harbour Crime) are
kept, as V1 offered them.

```bash
python manage.py seed data/seed/core/                        # defines `police_district`
python manage.py seed states.toml districts.toml             # IN_KERALA and its districts
python manage.py seed data/seed/kerala/police_stations.toml  # 517 stations
```

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
- `src/apps/locations/migrations/0004_location_type_bank.py`
- `src/apps/locations/migrations/0005_location_type_police_station.py`
- `data/seed/kerala/police_stations.toml`
- `data/seed/core/additional_attributes.toml`
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