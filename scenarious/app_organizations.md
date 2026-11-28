# Organizations scenarios

Scenario IDs for the organizations integration tests (spec 0008, marked per
spec 0037 §15). Each table row maps to a test tagged
`@pytest.mark.scenario("<ID>-<#>")` — row 2 of `ORG-HIERARCHY` is
`ORG-HIERARCHY-2`. IDs are assigned manually; once a test carries one it is
never renumbered or reused.

```bash
cd src
pytest --scenario ORG-HIERARCHY-2                              # run one scenario
pytest apps/organizations --scenario-report scenario-map.json  # regenerate the ID → test map
```

Per-endpoint success/shape/error coverage lives in
`apps/organizations/tests/test_organization_api.py` (spec 0000 §13). The
tables below pin only cross-call flows (spec 0037 §1): state seeded through
`manage.py seed`, hierarchy navigation across routes, and admin actions
between API calls.

Unless a row says otherwise, the seeded tree is spec 0008 §8's example data:
locations `IN` → `BR` → `PATNA`, then organizations `SUPREME_COURT_INDIA`
(jurisdiction `IN`) → `PATNA_HIGH_COURT` (jurisdiction `BR`) →
`PATNA_DISTRICT_COURT` (jurisdiction `PATNA`).

## Seeded organizations — read back over the API

ID: ORG-SEED
Endpoints: `GET /api/v1/organizations/` · `GET /api/v1/organizations/code/{code}/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | the locations TOML and organizations TOML seeded in that order (jurisdictions reference location codes) once per module | list organizations | 200, paginated envelope (`count`/`results`) with `meta`, all three seeded codes present |
| 2 | the seeded tree | fetch `PATNA_DISTRICT_COURT` by code | 200, `name`/`short_name`/`organization_type` verbatim from the TOML, `organization_type_display` = `"District Court"`, `parent_code` = `PATNA_HIGH_COURT`, `jurisdiction_codes` = `["PATNA"]` |
| 3 | the seeded tree | run `manage.py seed` again with the same files, then re-list | 200, `count` and rows unchanged — seeding is insert-only and re-running is safe (spec 0025) |
| 4 | the seeded tree | an anonymous client (no credentials) lists and fetches | all 200 — the read-only API allows anonymous safe methods, same as locations |

Notes:

- Seed once per module from `apps/organizations/tests/data/*.toml`; the
  module-scoped fixture must depend on `django_db_setup` (spec 0037 §7).
- Test codes must not collide with `data/seed/example/organizations.toml`
  (`KL_HC`, `ERN_DC`) — seeding is insert-only, so a collision silently
  keeps the existing row.
- The TOML files are the single source of truth: parse them back with
  `tomllib` and validate API output against file content.
- Tests: `apps/organizations/tests/integration/test_seeded_organizations_api.py`.

## Hierarchy navigation — children and ancestors by id and code

ID: ORG-HIERARCHY
Endpoints: `GET /api/v1/organizations/{id}/children/` · `GET /api/v1/organizations/code/{code}/children/` · `GET /api/v1/organizations/{id}/ancestors/` · `GET /api/v1/organizations/code/{code}/ancestors/` (spec 0008 §4–5)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | the seeded three-level tree | `GET /organizations/code/SUPREME_COURT_INDIA/children/` | 200, paginated, exactly the direct child `PATNA_HIGH_COURT` — the district court is not listed |
| 2 | the seeded tree | `GET /organizations/code/PATNA_DISTRICT_COURT/ancestors/` | 200, unpaginated `data` list ordered root-first: `SUPREME_COURT_INDIA`, `PATNA_HIGH_COURT` |
| 3 | the seeded tree | `GET /organizations/code/SUPREME_COURT_INDIA/ancestors/` | 200 with `data: []` — a root has no ancestors |
| 4 | the seeded tree | repeat rows 1–2 through the `{id}` routes | identical payloads — the id and code routes agree |
| 5 | the seeded tree | `GET /organizations/{id}/children/` for the district court (a leaf) | 200, `count` = 0, `results: []` |

Notes:

- Ancestor chains are returned whole (unpaginated); children are paginated
  like the list endpoint.
- Tests: `apps/organizations/tests/integration/test_hierarchy.py`.

## Jurisdiction mapping and filtering

ID: ORG-JURISDICTION
Endpoints: `GET /api/v1/organizations/` · `GET /api/v1/organizations/{id}/jurisdictions/` · `GET /api/v1/organizations/code/{code}/jurisdictions/` (spec 0008 §7)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | the seeded tree | `GET /organizations/?jurisdiction_code=BR` | 200, only `PATNA_HIGH_COURT` — the other two organizations map to different locations |
| 2 | the seeded tree | `GET /organizations/code/PATNA_HIGH_COURT/jurisdictions/` | 200, paginated list of **Location** objects (spec 0007's serializer: `code`, `location_type`, `parent_code`, `full_name`) — organizations reuse the location module instead of duplicating it |
| 3 | an organization seeded with no jurisdictions | its jurisdictions endpoint, then fetch by code | 200 with an empty page; the fetch shows `jurisdiction_codes: []` |
| 4 | the seeded tree | a superuser deactivates `BR` in the locations admin, then the row-1 filter and row-2 endpoint are repeated | both still return `BR` — the M2M mapping ignores location activity (pins current behavior; spec 0008 open question) |
| 5 | the seeded tree | `GET /organizations/?jurisdiction_id={uuid}&jurisdiction_code=BR` (both supplied) | 400 — `jurisdiction_id` and `jurisdiction_code` are mutually exclusive (same for the parent pair) |

Notes:

- Row 4 is the admin-between-calls shape crossing two apps: the edit happens
  in `locations`'s admin, the assertion lands on `organizations`'s API.
- Tests: `apps/organizations/tests/integration/test_jurisdictions.py`.

## Admin changes drive API behavior

ID: ORG-ADMIN
Endpoints: `/admin/organizations/organization/` · `GET /api/v1/organizations/` and its lookup routes (spec 0008 §6, spec 0037 §5)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | seeded locations | a superuser submits the admin add form for an **active** organization with no jurisdictions | the form re-renders with the "at least one jurisdiction" error, no row is created, and `GET /organizations/code/{code}/` is 404 |
| 2 | seeded locations | the add form is submitted **inactive** (`is_active` unchecked) with no jurisdictions | the organization is saved and appears under `?is_active=false`, not under `?is_active=true` |
| 3 | locations including a pincode, a bank and a police station | the superuser opens the add/change form's jurisdictions picker | only administrative areas are offered — leaf location types (pincode, bank, police station) never appear (spec 0007 §7–8) |
| 4 | an existing organization | the superuser changes its jurisdictions via the change-view POST | `GET /organizations/code/{code}/` shows the new `jurisdiction_codes` and the jurisdictions endpoint lists them |
| 5 | an organization with a child | the superuser deactivates the parent via the change-view POST | the parent is absent from `?is_active=true` and present under `?is_active=false`; its children routes keep resolving (children are listed regardless of the parent's activity) |
| 6 | a parent organization with children | the superuser confirms delete on the parent's admin delete page | the delete is refused (`ProtectedError`, `parent` is `PROTECT`) and parent + children remain readable over the API |
| 7 | the seeded tree | the superuser sets `PATNA_HIGH_COURT`'s parent to its own descendant `PATNA_DISTRICT_COURT` via the change form | form validation rejects the circular chain, the hierarchy is unchanged, and the ancestors endpoint returns the same chain as before |

Notes:

- Every row POSTs the real admin form (management-form data included) with a
  `force_login` superuser — never `objects.update()` behind the admin's back
  (spec 0037 §5, anti-pattern 4).
- Tests: `apps/organizations/tests/integration/test_organization_admin_flow.py`.
