# Seed data

TOML files loaded by the `seed` management command (spec 0025) to insert
**initial** reference data into an environment:

```sh
python manage.py seed data/seed/example/            # a directory of *.toml
python manage.py seed data/seed/example/locations.toml   # a single file
python manage.py seed --list                        # list seedable models
```

Seeding is **insert-only**: a row whose natural key already exists is left
exactly as it is. Changing seeded data is a manual admin task.

## File format

Each file names its target model in a `[seed]` table and lists rows under
`[[rows]]`:

```toml
[seed]
model = "locations.Location"   # app_label.ModelName (see `seed --list`)

[[rows]]
code = "IN"
name = "India"
location_type = "country"

[[rows]]
code = "IN_KL"
name = "Kerala"
location_type = "state"
parent = "IN"                  # a foreign key given as the parent's code
```

- **Foreign keys** (`parent`, …) are given as the related row's natural key.
- **Many-to-many** fields take a list of codes, e.g. an organization's
  `jurisdictions = ["IN_KL"]` or a page's `categories = ["help"]`.
- A referent may be defined earlier in the same file, or already exist in the
  database. An unresolved reference skips just that row.
- Across models, referents load first (locations before organizations, page
  categories before pages), so a whole directory can be seeded in one run.
- For several files of the **same** model, they load in the order you pass
  them, so dependent data can be split across files, e.g.
  `seed states.toml districts.toml pincodes.toml`. (Files picked up from a
  directory load in sorted-name order.)
- **JSON fields** (`data_schema`, `schema`, `condition`, `rule_input_schema`,
  …) are written as TOML tables or inline tables. A text field holding JSON
  (`config_value`, a gorules `rule_expression`) is written as a JSON string,
  for a long one a multi-line literal string (`'''{ ... }'''`).

Run `seed --list` for every seedable model and its natural key.

### Foreign keys in the natural key

Some models are identified partly by a foreign key, which is given by the
related row's natural key. An approval step is keyed by its request type's code
and its order:

```toml
[seed]
model = "dristi_requests.ApprovalStep"

[[rows]]
request_type = "LAWYER_BAR_UPDATE"   # RequestType.code
order = 0
approver_role = "BAR_ID_APPROVER"
approver_group = "BAR_ID_APPROVER"   # auth.Group.name
```

A nullable foreign key in the key may be left out, and then matches NULL. A
scrutiny rule binding without an `organization` is the national default:

```toml
[seed]
model = "scrutiny.ScrutinyRuleBinding"

[[rows]]
decision = "CHECKS"                  # no organization: national default
rule_code = "SCRUTINY_CHECKS_DEFAULT"
```

The `example/` folder is a small, self-contained set used by the tests and as a
worked example of the format.

## Initial data every environment needs

`core/` holds reference data the application needs in every environment,
seeded instead of shipped as data migrations:

- `core/languages.toml` — the supported languages and the default one
  (spec 0030). Language resolution fails until it is loaded.
- `core/public_configurations.toml` — per-state switches and e-filing
  drop-down options the frontend reads from the public configuration API
  (spec 0034), seeded with Kerala's values.
  `ui_efiling.natively_digital_document_submission_on` shows the natively
  digital question on e-filing documents; a state that does not need it sets
  the row to `false` in the admin (re-seeding never overwrites it).
  The `*_drop_down` rows (entity types and the cheque bounce evidence lists)
  each mirror a backend enum; change both together
  (`apps/cases/tests/test_drop_down_seed.py` checks they match). Seeding is
  insert-only, so an environment that already has a row needs the change made
  in admin as well.
- `core/configurations.toml` — `tenant.state_code`, the state code that
  prefixes request numbers (`KL-REQ-00001`, spec 0010). Creating a request
  fails until it is loaded.
- `core/additional_attributes.toml` — the additional attributes each model
  accepts, e.g. a bank location's `address` (issue #249) and a police
  station's `police_district` (issue #250). A row's
  `additional_attributes` are rejected until their keys are defined, so this
  loads before other models whatever order the files are given in.
- `core/auth/groups.toml` — `BAR_ID_APPROVER` and the placeholder court-role
  groups used by hearings.
- `core/cms/` — the default page categories and placeholder pages.
- `core/dristi_requests/` — the request types (lawyer bar update, advocate and
  clerk registration) and their approval steps.
- `core/hearings/hearing_purposes.toml` — the hearing purposes.
- `core/messaging/` — the SMS templates (account, case filing, hearings).
- `core/scrutiny/` — the national `SCRUTINY_CHECKS_DEFAULT` rule and its
  binding.

This data used to be inserted by data migrations (spec 0036). Add new
reference data here, not in a migration.

```sh
python manage.py seed data/seed/core/
```

## Bar-ID approvers (local / test)

Registration and bar-ID requests route their approval step to the
`BAR_ID_APPROVER` group. The core seed (`core/auth/groups.toml`) creates that
group empty, so a fresh stack cannot route a request until someone is a member. `local/bar_id_approvers.toml`
adds the user with mobile number `+919999999999`:

```sh
python manage.py createsuperuser        # mobile number +919999999999
python manage.py seed data/seed/local/
```

The file seeds `users.User_groups` (a user-group membership). Users are matched
by `mobile_number` and groups by `name`, and both must already exist; an unknown
one skips the row. To make someone else an approver, add a row with their
number. A requester is never their own approver, so register with a different
number.

## Court levels, roles and assignments (spec 0029)

Court access is per environment, so nothing here is in `core/`. Mark an
organization's place in the court hierarchy with `court_level`
(`ESTABLISHMENT`, or `COURTROOM` under an establishment):

```toml
[seed]
model = "organizations.Organization"

[[rows]]
code = "ERN_NI_COURT"
organization_type = "magistrate_court"
name = "NI Act Court, Ernakulam"
parent = "ERN_DC"
court_level = "ESTABLISHMENT"

[[rows]]
code = "ERN_NI_COURT_CR1"
organization_type = "magistrate_court"
name = "Courtroom 1"
parent = "ERN_NI_COURT"
court_level = "COURTROOM"
```

Roles (`organizations.CourtRole`) are keyed by `code` and `establishment`; leave
`establishment` out for a deployment-wide role. Their actions
(`organizations.CourtRoleAction`) name the role as `CODE`, or
`CODE.ESTABLISHMENT_CODE` for an establishment's own role, and an action
declared in some app's `court_actions.py`:

```toml
[seed]
model = "organizations.CourtRoleAction"

[[rows]]
role = "BENCH_CLERK"
action = "process.sign"
scope = { process_types = ["NOTICE", "SUMMONS"] }
```

Test accounts get access with `organizations.CourtroomAssignment` (`user` by
mobile number, `courtroom` by code), then `organizations.RoleAssignment`
(`user`, `organization`, `role`). A role at a courtroom needs the courtroom on
the user's list first; the files load in that order. Seeding is insert-only:
change roles and assignments in admin afterwards.

## Loading pincodes

Pincodes (and the states and districts above them) are loaded from TOML like
any other locations. The raw `states.toml`, `districts.toml` and
`pincodes.toml` — and the one-time CSV-to-TOML converter that builds them from
India Post's directory — live in the
[`dristi-be-experiments`](https://github.com/pucardotorg/dristi-be-experiments)
repo (they may move to a dedicated seed-data repo later). Load them in order:

```sh
python manage.py seed states.toml districts.toml pincodes.toml
```

`states.toml` must load first, then `districts.toml` (whose `parent` is a state
code), then `pincodes.toml` (whose `parent` is a district code).

## Loading banks

Bank branches (issue #249, spec 0007 section 8) are `bank` locations keyed by
IFSC, each under its district. Only Kerala is seeded for now:
`banks_kerala.toml` is generated from
[razorpay/ifsc](https://github.com/razorpay/ifsc) by `ifsc_to_toml.py` (in
`dristi-be-experiments`, next to the pincode converter) and loaded after
`core/additional_attributes.toml` (which defines `address`) and the Kerala
districts:

```toml
[[rows]]
code = "AUBL0002670"
name = "AU Small Finance Bank - M G ROAD KOCHI"
short_name = "AUBL0002670"
location_type = "bank"
parent = "IN_KERALA_ERNAKULAM"
additional_attributes = { address = "BUILDING DOOR NOS. 62/5202 ..., MG ROAD, KOCHI, KERALA" }
```

```sh
python manage.py seed data/seed/core/
python manage.py seed states.toml districts.toml
python manage.py seed banks_kerala.toml
```

Locations load in batches, so the ~9,000 Kerala banks take about 10 seconds.

## Loading police stations

Police stations (issue #250, spec 0007 section 9) are `police_station`
locations keyed by their 8-digit code from V1's MDMS master, each under its
revenue district (railway police and CID under the state). Only Kerala is
seeded: `kerala/police_stations.toml` is kept in this repo and loads after
`core/` (which defines `police_district`) and the Kerala state and districts:

```toml
[[rows]]
code = "15996001"
name = "THRISSUR EAST"
location_type = "police_station"
parent = "IN_KERALA_THRISSUR"
additional_attributes = { police_district = "THRISSUR CITY" }
```

```sh
python manage.py seed data/seed/core/
python manage.py seed states.toml districts.toml
python manage.py seed data/seed/kerala/police_stations.toml
```
