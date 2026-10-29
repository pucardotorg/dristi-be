# 0025 — Data Seeding Command

## Status

Proposed

> Tracks [#169](https://github.com/pucardotorg/dristi-be/issues/169). Reviewed; review decisions folded into the spec (see Resolved decisions).

## Context

Reference data that an environment needs before it can serve traffic — locations, organizations, business rules, configurations, CMS pages and similar — currently arrives two ways: some through ad-hoc data migrations, the rest entered by hand. Neither is reviewable, repeatable, or portable between environments. Bringing up a new jurisdiction means re-doing manual work, and there is no single human-readable record of what "initial data" an environment is supposed to hold.

We already have a proven pattern for one slice of this problem: `apps.locations.management.commands.import_pincodes` reads a file, matches existing rows by a natural key, creates missing rows and their relationships, preserves manual edits, and supports `--dry-run`. This spec generalizes that pattern into a single `seed` command that works across the reference-data models.

## Goals

- Provide one `manage.py seed <file>...` command that loads initial reference data from human-readable TOML files.
- Be **idempotent**: re-running the same file(s) makes no further changes and never creates duplicates.
- **Seed only** — insert rows that are missing. Existing rows are left untouched; updates stay a manual/admin task.
- Resolve **relationships** by natural key (parent locations, parent organizations, a page's category, an organization's locations).
- Keep seed data portable so it can live in a separate per-jurisdiction data repo (`<<data-repo>>/gj/locations.toml`, `<<data-repo>>/kl/locations.toml`), and accept either files or a directory of them.
- Report clearly what was created, what already existed, and what could not be resolved; support `--dry-run` and listing the seedable models.

## Non-goals

- Updating or reconciling existing rows (insert-only: no upsert of changed fields, no deletes). Changing seeded data is done manually in the admin.
- A full fixtures/ORM-dump replacement. This is for curated, human-maintained reference data, not arbitrary table dumps.
- Seeding transactional/domain data (cases, filings, users, payments).
- A GUI or API for seeding. It is a management command only.
- Managing the external data repo itself (layout, versioning, access).

## Design overview

A single `seed` command dispatches each input TOML file to a **per-model seeder**. The command owns everything generic — path/file parsing, transactions, idempotency bookkeeping, relationship resolution by code, reporting, `--dry-run`, and `--list` (print the registered seedable models). Each seeder is a small declarative registration that says: which model, which natural key, which fields, and which fields are foreign keys resolved by code. TOML is read with the standard library's `tomllib` (Python 3.11+, which the project requires).

```
manage.py seed  <file>...  [options]
```

### 1. Command location and layout

A new app-neutral command lives in `core` (the home of the shared base models):

```
src/apps/core/management/
├── __init__.py
└── commands/
    ├── __init__.py
    └── seed.py          # Command + generic engine
src/apps/core/seeding/
├── __init__.py
├── registry.py          # SeedSpec dataclass + register()/lookup
└── specs.py             # one SeedSpec per seedable model
```

Per-model seeders are declared centrally in `core/seeding/specs.py` so the set of seedable entities is discoverable in one place. (Alternative considered: a `seeding.py` per app, auto-discovered. Rejected for v1 to keep the registry explicit and reviewable.)

### 2. Choosing the target model for a file

Each input file declares its target model in a small `[seed]` header, so a file is self-describing and `seed` needs no `--model` flag:

```toml
[seed]
model = "locations.Location"   # app_label.ModelName
key   = "code"                 # optional override of the spec's default key

[[rows]]
code = "KL"
name = "Kerala"
location_type = "state"
parent = "IN"                  # resolved to Location(code="IN")

[[rows]]
code = "KL_ERN"
name = "Ernakulam"
location_type = "district"
parent = "KL"
```

The declared `model` must resolve to a registered `SeedSpec`; an unknown or unregistered model is a `CommandError` naming the registered models. A file with no `[seed].model`, or no `[[rows]]`, is likewise a `CommandError`.

### 3. `SeedSpec`

```python
@dataclass(frozen=True)
class SeedSpec:
    model: type[Model]
    key: tuple[str, ...]          # natural-key field(s), e.g. ("code",)
    fields: tuple[str, ...]       # scalar fields allowed in a row
    fk_by_code: dict[str, FkRef]  # field -> (related model, its key field)
    m2m_by_code: dict[str, FkRef] # field -> related model for list-valued M2M
    order: int = 0                # relative load order across files (low first)
```

`FkRef` captures the related model and the field its code is matched on. A seeder registration is pure data; it carries no procedural logic. Validation of each row runs through the model's own `full_clean()`, so every existing constraint (code format, additional-attribute schemas, hierarchy checks) is enforced for free.

### 4. Registered seeders (v1)

Natural keys below are taken from the current models.

| `model` | Natural key | FK-by-code | M2M-by-code | Notes |
|---|---|---|---|---|
| `locations.Location` | `code` | `parent` → Location.code | — | Self-referential hierarchy; parent must load first (same or earlier file). |
| `organizations.Organization` | `code` | `parent` → Organization.code | `locations` → Location.code | `code` is uppercase snake_case. |
| `core.BusinessRule` | `code` | — | — | `code` uppercase snake_case. |
| `core.Configuration` | `(config_set, config_key)` | — | — | Composite key; both normalized by the model. `config_value` is coerced to its stored type (see below). |
| `cms.PageCategory` | `slug` | — | — | `name` also unique. |
| `cms.Page` | `slug` | `category` → PageCategory.slug | — | Slug lowercased by the model. |

"Permissions" from the ticket are **out of scope** for now (confirmed by @thejeshgn); current `users.Role` is a code-level `TextChoices`, not a seedable row set.

Values from TOML are **coerced to each field's type** before validation (e.g. `Configuration.config_value` to its stored representation), so the file can stay in native TOML types. Coercion reuses the model field's `to_python`/`clean`, and a value that will not coerce is reported as a row error rather than silently stored.

### 5. Idempotency

For each row the engine computes the natural key and looks up an existing record:

- **Not found** → create it (collecting for a `bulk_create`, or `create()` where a model needs `save()` side effects / `full_clean`).
- **Found** → count as *unchanged* and skip. The engine never writes to an existing row. This is **insert-only**: a field changed in the file after first load will **not** propagate — updates and deletes are done manually in the admin, per the ticket. Reporting surfaces the skip so it is not silently surprising.

Re-running any file therefore converges to zero writes. A composite key (Configuration) is matched on the tuple.

### 6. Relationship resolution

- FK fields named in `fk_by_code` take a code string in the file and resolve to the related object by its key. A referent may be defined earlier **in the same file** (rows are processed in file order, and self-referential parents are loaded parent-before-child) or already exist in the DB.
- M2M fields (`Organization.locations`) take a list of codes, resolved and set after the owning row is created.
- An unresolved reference is reported per `(file, row key, field, value)` and that row is skipped; it is never silently created as a stub.

### 7. Load order across files

When multiple files are passed, they are grouped by target model and loaded in each spec's `order` (locations before organizations, categories before pages). Within the engine everything runs in **one transaction**, so a later failure rolls the whole run back — a partial seed never lands. `--dry-run` sets a rollback at the end so a full run can be previewed, created relationships included (same approach as `import_pincodes`).

### 8. CLI

```
manage.py seed PATH [PATH ...]
    --list           Print the registered seedable models and exit.
    --dry-run        Report what would be created without saving.
    --strict         Treat any unresolved reference or skipped row as an error
                     (non-zero exit), instead of warning and continuing.
    -v 2             List every created row and every unresolved reference.
```

Each `PATH` is a TOML file **or a directory**; a directory loads every `*.toml` under it, sorted, recursively. This lets a whole jurisdiction be seeded by pointing at one folder.

Examples:

```sh
# Single file (as in the ticket)
python manage.py seed ./data/test/locations.toml

# A whole jurisdiction from the external data repo (directory)
python manage.py seed  <<data-repo>>/kl/

# Or several explicit files
python manage.py seed  <<data-repo>>/kl/locations.toml  <<data-repo>>/kl/organizations.toml

# List what can be seeded
python manage.py seed --list
```

### 9. Reporting

Per file and as a run total: `created`, `unchanged` (already present), `skipped` (unresolved references), with a one-line `SUCCESS`/`WARNING` summary mirroring `import_pincodes`. At `-v 2`, each created row's key and each unresolved reference are listed. `--dry-run` prefixes counts with "Dry run: would have…".

## Testing

- Unit tests per registered seeder: create-from-empty, re-run-is-noop (idempotency), existing row left untouched (insert-only), FK/M2M resolution by code, unresolved reference handling, composite-key match (Configuration), `config_value` coercion.
- Engine tests: `[seed]` header parsing, missing-header/empty-rows errors, unknown model error, directory expansion to `*.toml`, multi-file load order, `--list` output, `--dry-run` rolls back, `--strict` exit code, transaction rollback on mid-run failure.
- A small fixture seed set under `src/data/seed/` used by tests and as living documentation of the file format.

## Rollout

1. Engine + registry + `locations.Location` and `organizations.Organization` seeders (highest-value, exercise FK + M2M + self-reference).
2. `core.Configuration`, `core.BusinessRule`.
3. `cms.PageCategory`, `cms.Page`.
4. Document the file format and the external-data-repo layout in `docs/development.md`.

## Resolved decisions

All open questions were resolved in review by @thejeshgn:

1. **Single `seed` command** (one self-describing command), with `--list` to show the registered seedable models — preferred over per-entity commands. See §2, §8.
2. **TOML only**, per the ticket. CSV is out of scope; `import_pincodes` keeps its own CSV reader for the India Post directory.
3. **Permissions out of scope** for now. See §4.
4. **`config_value` is coerced** to its stored type; the file stays in native TOML types. See §4.
5. **Insert-only** — no upsert, no deletes. Updates are manual. See §5.
6. **A `PATH` may be a directory**, loading every `*.toml` under it. See §8.
