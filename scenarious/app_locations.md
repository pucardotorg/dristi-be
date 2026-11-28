# Locations scenarios

Scenario IDs for the locations integration tests (spec 0007, marked per spec
0037 §15). Each table row maps to a test tagged
`@pytest.mark.scenario("<ID>-<#>")` — row 2 of `LOC-PINCODE` is
`LOC-PINCODE-2`. IDs are assigned manually; once a test carries one it is
never renumbered or reused.

```bash
cd src
pytest --scenario LOC-PINCODE-2                              # run one scenario
pytest apps/locations --scenario-report scenario-map.json    # regenerate the ID → test map
```

Per-endpoint success/shape/error coverage lives in
`apps/locations/tests/test_location_api.py` (spec 0000 §13). The tables below
pin only cross-call flows (spec 0037 §1): state seeded through `manage.py
seed`, multi-request client sequences, and admin actions between API calls.

## Seeded hierarchy — read back over the API

ID: LOC-SEED
Endpoints: `GET /api/v1/locations/` · `GET /api/v1/locations/code/{code}/` · `GET /api/v1/locations/code/{code}/children/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `data/seed/core/additional_attributes.toml` + a test TOML seeding `IN` (country) → `IN_KL` (state) → `IN_KL_ERN` (district) → `PIN_682001` (pincode), loaded once per module via `manage.py seed` | list locations | 200, paginated envelope (`count`/`results`) with `meta`, the four seeded codes present, ordered by `code` |
| 2 | the seeded hierarchy | fetch `IN_KL_ERN` by code | 200, `name`/`short_name`/`location_type` verbatim from the TOML, `parent_code` = `IN_KL`, `full_name` = `"India / Kerala / Ernakulam"`, `additional_attributes` carries `"address": null` and `"police_district": null` |
| 3 | the seeded hierarchy | run `manage.py seed` again with the same files, then re-list | 200, `count` and rows unchanged — seeding is insert-only and re-running is safe (spec 0007 §7) |
| 4 | the seeded hierarchy | `GET /locations/code/IN/children/?location_type=state` | 200 with exactly `IN_KL`; with `location_type=district` an empty page — children are direct only |
| 5 | the seeded hierarchy | an anonymous client (no credentials) makes the list, fetch, children and ancestors calls | all 200 — the read-only location endpoints are public by design in v1 (spec 0007 §6) |
| 6 | a test TOML whose pincode row names a state as `parent` | `manage.py seed` | the row is skipped with a warning (model `clean()` rejects it), the valid rows still load, and the bad code is absent from the API |

Notes:

- Seed once per module from `apps/locations/tests/data/*.toml`, always after
  `data/seed/core/additional_attributes.toml` so the `address` and
  `police_district` keys exist (spec 0007 §8–9). The module-scoped fixture
  must depend on `django_db_setup` (spec 0037 §7).
- The TOML files are the single source of truth: parse them back with
  `tomllib` and validate API output against file content, as in
  `apps/cms/tests/test_seeded_pages_api.py`.
- Test codes must not collide with `data/seed/kerala/police_stations.toml` or
  the example TOMLs — seeding is insert-only, so a collision silently keeps
  the existing row.
- Tests: `apps/locations/tests/integration/test_seeded_locations_api.py`.

## Pincode pre-fill for address forms

ID: LOC-PINCODE
Endpoints: `GET /api/v1/locations/code/{code}/ancestors/` (spec 0007 §7)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | the all-active chain `IN` → `IN_KL` → `IN_KL_ERN` → `PIN_682001` | `GET /locations/code/PIN_682001/ancestors/?is_active=true` | 200, unpaginated `data` list ordered root-first (country, state, district) with `meta`; the entries whose `location_type` is `district` and `state` are the pre-fill values |
| 2 | the same chain | a superuser deactivates `IN_KL_ERN` through the admin change view, then the call is repeated | 404 — one inactive link breaks the chain; the form falls back to manual entry |
| 3 | the same chain | the pincode itself is deactivated in admin, then the call is repeated | 404 — the location itself must be active |
| 4 | an inactive pincode under the active chain | `GET .../ancestors/?is_active=false` | 200 — `false` finds only an inactive location, chain included |
| 5 | the active chain | `?is_active=` (empty), then `?is_active=yes` | the empty value is treated as not sent (200); `yes` is a 400 with field `is_active` — a typo never skips the active check |

Notes:

- Rows 2–3 are the admin-between-calls shape (spec 0037 §5): Django `Client`
  with a `force_login` superuser POSTs the real change view; the API client
  then re-reads.
- A 404 on this route is a contract, not a failure: it means "no pre-fill",
  and the user types district and state by hand.
- Tests: `apps/locations/tests/integration/test_pincode_prefill.py`.

## Bank branch lookup by IFSC

ID: LOC-BANK
Endpoints: `GET /api/v1/locations/code/{code}/` (spec 0007 §8)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | the seeded `address` attribute, district `IN_KL_ERN`, and an active bank `AUBL0002670` carrying an `address` | `GET /locations/code/AUBL0002670/?location_type=bank&is_active=true` | 200, `code`/`short_name` = the IFSC, `name` = `<BANK> - <BRANCH>` verbatim from the TOML, `parent_code` = `IN_KL_ERN`, `additional_attributes.address` verbatim |
| 2 | the same bank | the branch is deactivated in admin (a closed branch), then the call is repeated | 404 — "no pre-fill"; the user enters bank and branch by hand |
| 3 | the seeded district | `GET /locations/code/IN_KL_ERN/?location_type=bank` | 404 — the code exists but is not a bank |
| 4 | the active bank | `GET /locations/code/aubl0002670/?location_type=bank&is_active=true` (lowercase) | 404 — the client uppercases the IFSC before calling |
| 5 | an active bank seeded with no `address` row | the standard lookup | 200, `additional_attributes.address` is `null` — the attribute is defined but optional |

Notes:

- The seed order matters: `additional_attributes.toml` (defines `address`),
  then states/districts, then banks — the production load order from spec
  0007 §8.
- Tests: `apps/locations/tests/integration/test_bank_lookup.py`.

## Police-station suggestions for a district

ID: LOC-POLICE
Endpoints: `GET /api/v1/locations/` · `GET /api/v1/locations/code/{code}/ancestors/` (spec 0007 §9)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | district `IN_KL_TSR` with stations `15996001` and `15996002` (one inactive) plus a state-wide railway-police station under `IN_KL` | `GET /locations/?parent_code=IN_KL_TSR&location_type=police_station&is_active=true&page_size=100` | 200, exactly the active district stations, each carrying `additional_attributes.police_district`; the inactive station and the state-wide unit are absent |
| 2 | a pincode seeded under `IN_KL_TSR` | the client resolves `GET /locations/code/{pincode}/ancestors/?is_active=true`, takes the `district` entry's code, then lists that district's stations as in row 1 | the two-call sequence returns the district's stations (pincode pre-fill + station suggestion, issue #250) |
| 3 | a district with 25 seeded active stations | the row-1 list call with `page_size=100` | 200, `count` = 25 and all 25 in one page — a dropdown loads a whole district in one request (default page size is 20) |

Notes:

- The station list is a suggestion only; filing never checks it. The scenario
  pins the read contract, not any filing behavior.
- Tests: `apps/locations/tests/integration/test_police_stations.py`.

## Admin changes drive API behavior

ID: LOC-ADMIN
Endpoints: `/admin/locations/location/` · `GET /api/v1/locations/` and its lookup routes (spec 0007 §5, spec 0037 §5)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | an active state with active districts | a superuser deactivates the state via the admin change-view POST | `GET /locations/{id}/children/` and `GET /locations/code/{code}/children/` return 404; the plain by-code fetch still returns 200 with `is_active: false`, and the same fetch with `?is_active=true` is a 404 |
| 2 | a state with districts under it | the superuser confirms delete on the state's admin delete page | the protected-children message is shown and state + districts remain fetchable over the API (`parent` is `PROTECT`) |
| 3 | a leaf pincode | the superuser deletes it via admin | the delete succeeds and `GET /locations/code/{code}/` is 404 afterwards |
| 4 | the admin add form (parametrized: pincode under a state; any location under a pincode; bank whose code is not an IFSC; police station whose code is not 8 digits; lowercase `code`) | the superuser submits the form | the form re-renders with a field error, nothing is saved, and the API is unchanged — `clean()` rules hold on the admin surface |
| 5 | a district that holds pincodes | the superuser edits its `location_type` to `state` via the change view | the form rejects it ("must stay a district"), the row is unchanged, and the pincodes' ancestor lookups still resolve |

Notes:

- Every row POSTs the real admin form (management-form data included) with a
  `force_login` superuser — never `objects.update()` behind the admin's back
  (spec 0037 §5, anti-pattern 4).
- Tests: `apps/locations/tests/integration/test_location_admin_flow.py`.
