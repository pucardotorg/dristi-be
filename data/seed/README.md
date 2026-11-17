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

The `example/` folder is a small, self-contained set used by the tests and as a
worked example of the format.

## Initial data every environment needs

`core/` holds reference data the application needs in every environment,
seeded instead of shipped as data migrations:

- `core/languages.toml` — the supported languages and the default one
  (spec 0030). Language resolution fails until it is loaded.
- `core/additional_attributes.toml` — the additional attributes each model
  accepts, e.g. a bank location's `address` (issue #249). A row's
  `additional_attributes` are rejected until their keys are defined, so this
  loads before other models whatever order the files are given in.

```sh
python manage.py seed data/seed/core/
```

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
IFSC, converted from [razorpay/ifsc](https://github.com/razorpay/ifsc) and
loaded after `core/additional_attributes.toml` (which defines `address`) and
the states or districts they point at:

```toml
[[rows]]
code = "ICIC0000002"
name = "ICICI Bank - BANGALORE M G ROAD"
short_name = "ICIC0000002"
location_type = "bank"
parent = "IN_KA"
additional_attributes = { address = "ICICI BANK LTD., 1, SHOBHA PEARL, ..." }
```

Locations load in batches, so the full list (about 1.8 lakh rows) takes about a
minute.
