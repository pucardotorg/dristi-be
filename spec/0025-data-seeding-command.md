# 0025 — Data Seeding Command

## Status

Proposed

> Tracks [#169](https://github.com/pucardotorg/dristi-be/issues/169). Shared for review before implementation.

## Context

Reference data that an environment needs before it can serve traffic — locations, organizations, business rules, configurations, CMS pages and similar — currently arrives two ways: some through ad-hoc data migrations, the rest entered by hand. Neither is reviewable, repeatable, or portable between environments. Bringing up a new jurisdiction means re-doing manual work, and there is no single human-readable record of what "initial data" an environment is supposed to hold.

We already have a proven pattern for one slice of this problem: `apps.locations.management.commands.import_pincodes` reads a file, matches existing rows by a natural key, creates missing rows and their relationships, preserves manual edits, and supports `--dry-run`. This spec generalizes that pattern into a single `seed` command that works across the reference-data models.

## Goals

- Provide one `manage.py seed <file>...` command that loads initial reference data from human-readable TOML files.
- Be **idempotent**: re-running the same file(s) makes no further changes and never creates duplicates.
- **Seed only** — insert rows that are missing. Existing rows are left untouched; updates stay a manual/admin task.
- Resolve **relationships** by natural key (parent locations, parent organizations, a page's category, an organization's locations).
- Keep seed data portable so it can live in a separate per-jurisdiction data repo (`<<data-repo>>/gj/locations.toml`, `<<data-repo>>/kl/locations.toml`).
- Report clearly what was created, what already existed, and what could not be resolved; support `--dry-run`.

## Non-goals

- Updating or reconciling existing rows (no upsert of changed fields, no deletes). Changing seeded data is done manually in the admin.
- A full fixtures/ORM-dump replacement. This is for curated, human-maintained reference data, not arbitrary table dumps.
- Seeding transactional/domain data (cases, filings, users, payments).
- A GUI or API for seeding. It is a management command only.
- Managing the external data repo itself (layout, versioning, access).

## Design overview

A single `seed` command dispatches each input TOML file to a **per-model seeder**. The command owns everything generic — file parsing, transactions, idempotency bookkeeping, relationship resolution by code, reporting, `--dry-run`. Each seeder is a small declarative registration that says: which model, which natural key, which fields, and which fields are foreign keys resolved by code. TOML is read with the standard library's `tomllib` (Python 3.11+, which the project requires).

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
| `core.Configuration` | `(config_set, config_key)` | — | — | Composite key; both normalized by the model. |
| `cms.PageCategory` | `slug` | — | — | `name` also unique. |
| `cms.Page` | `slug` | `category` → PageCategory.slug | — | Slug lowercased by the model. |

"Permissions" from the ticket are **deferred** — see Open Questions; current `users.Role` is a code-level `TextChoices`, not a seedable row set.

### 5. Idempotency

For each row the engine computes the natural key and looks up an existing record:

- **Not found** → create it (collecting for a `bulk_create`, or `create()` where a model needs `save()` side effects / `full_clean`).
- **Found** → by default, count as *unchanged* and skip (insert-only, the seed-only rule). With `--upsert`, update the row's fields to match the file (relationships re-resolved too) and count it as *updated*.

Without `--upsert`, re-running a file converges to zero writes; with `--upsert`, re-running is still idempotent because an unchanged row produces no update. A composite key (Configuration) is matched on the tuple.

### 6. Relationship resolution

- FK fields named in `fk_by_code` take a code string in the file and resolve to the related object by its key. A referent may be defined earlier **in the same file** (rows are processed in file order, and self-referential parents are loaded parent-before-child) or already exist in the DB.
- M2M fields (`Organization.locations`) take a list of codes, resolved and set after the owning row is created.
- An unresolved reference is reported per `(file, row key, field, value)` and that row is skipped; it is never silently created as a stub.

### 7. Load order across files

When multiple files are passed, they are grouped by target model and loaded in each spec's `order` (locations before organizations, categories before pages). Within the engine everything runs in **one transaction**, so a later failure rolls the whole run back — a partial seed never lands. `--dry-run` sets a rollback at the end so a full run can be previewed, created relationships included (same approach as `import_pincodes`).

### 8. CLI

```
manage.py seed FILE [FILE ...]
    --upsert         Also update existing rows to match the file.
                     Default is insert-only (existing rows are skipped).
    --dry-run        Report what would change without saving.
    --strict         Treat any unresolved reference or skipped row as an error
                     (non-zero exit), instead of warning and continuing.
    -v 2             List every created/updated row and every unresolved reference.
```

Examples:

```sh
# Single file (as in the ticket)
python manage.py seed ./data/test/locations.toml

# A jurisdiction from the external data repo, several entities at once
python manage.py seed  <<data-repo>>/kl/locations.toml  <<data-repo>>/kl/organizations.toml
```

### 9. Reporting

Per file and as a run total: `created`, `updated` (with `--upsert`), `unchanged` (already present), `skipped` (unresolved references), with a one-line `SUCCESS`/`WARNING` summary mirroring `import_pincodes`. At `-v 2`, each created/updated row's key and each unresolved reference are listed. `--dry-run` prefixes counts with "Dry run: would have…".

## Testing

- Unit tests per registered seeder: create-from-empty, re-run-is-noop (idempotency), existing row skipped by default, updated with `--upsert`, FK/M2M resolution by code, unresolved reference handling, composite-key match (Configuration).
- Engine tests: `[seed]` header parsing, missing-header/empty-rows errors, unknown model error, multi-file load order, `--dry-run` rolls back, `--strict` exit code, transaction rollback on mid-run failure.
- A small fixture seed set under `src/data/seed/` used by tests and as living documentation of the file format.

## Rollout

1. Engine + registry + `locations.Location` and `organizations.Organization` seeders (highest-value, exercise FK + M2M + self-reference).
2. `core.Configuration`, `core.BusinessRule`.
3. `cms.PageCategory`, `cms.Page`.
4. Document the file format and the external-data-repo layout in `docs/development.md`.

## Open questions

1. **Single `seed` command vs. per-entity commands.** This spec proposes one self-describing command (matches the ticket's `seed <file>` example). Confirm that is preferred over `seed_locations`, `seed_orgs`, etc.
2. ~~**TOML and CSV, or TOML only?**~~ **Resolved: TOML only**, per the ticket. CSV is out of scope; `import_pincodes` keeps its own CSV reader for the India Post directory.
3. **"Permissions" scope.** Are these DB-backed rows to seed, or the code-level `users.Role` choices (not seedable)? Deferred until clarified.
4. **Config value typing in TOML.** `Configuration.config_value` — stored as-is from TOML (native types) or always coerced? Need the field's current type to finalize.
5. ~~**Edit preservation vs. pure seed-only.**~~ **Resolved** (@thejeshgn): default is insert-only, with an opt-in `--upsert` flag to also update existing rows. See §5 and §8.
6. **External data repo** — is it in scope to define its directory layout and wire a default `--from <dir>`, or is that a follow-up?
