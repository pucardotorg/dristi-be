# Migration cleanup

## 1. Goal

1. Move every piece of reference data that is now written by a data migration
   (`RunPython`) into TOML files under `../data/seed`, loaded by the existing
   `seed` management command (spec 0025, `apps/core/management/commands/seed.py`).
2. Delete every migration under `src/apps/*/migrations/` and regenerate one clean
   set of initial migrations from the current models.

This is safe now because the project has **never been deployed**: no environment
has a migration history we need to keep. Every developer and shared dev/staging
database will need a reset (see section 7).

The work is split into two phases (details in section 9):

| Phase | Scope | Sections |
|---|---|---|
| **Phase 1 — seed engine** | Teach `manage.py seed` to load every kind of reference data the migrations now insert. No data files, migrations, test fixtures or deployment scripts change. | 4, 9.1 |
| **Phase 2 — data move and migration reset** | Port the data to TOML, seed it in tests, delete and regenerate migrations, roll out, update docs. | 3, 5, 6, 7, 8, 9.2 |


## 2. Current state (inventory)

Checked on the current tree:

- `makemigrations --check --dry-run` reports **No changes detected**, so the
  models and migrations agree. Regenerating will not hide any pending change.
- No migration uses `RunSQL`, `SeparateDatabaseAndState`, PostgreSQL extensions
  or concurrent indexes. Nothing hand-written has to be carried over by hand
  except the data migrations listed below.
- Addons (`src/addon/*`) have no migrations, and their isolation tests require
  that. They are not affected.
- `apps.api` has no models or migrations.

### 2.1 Migrations per app

| App | Files | Schema migrations | Data migrations (`RunPython`) |
|---|---|---|---|
| address | 2 | 0001, 0002 | — |
| cases | 10 | 0001–0010 | — |
| cms | 2 | 0001 | **0002_seed_default_pages** |
| core | 8 | 0001–0008 | — |
| dristi_requests | 3 | 0001, 0003 | **0002_seed_lawyer_bar_update** |
| esign | 1 | 0001 | — |
| files | 1 | 0001 | — |
| hearings | 9 | 0001, 0003–0007 | **0002_seed_hearing_purposes**, **0008_seed_hearing_message_templates**, **0009_seed_hearing_role_groups** |
| locations | 3 | 0001–0003 | — |
| messaging | 7 | 0001–0003, 0006, 0007 | 0004_enforce_uppercase_message_keys (data fix + constraints), **0005_seed_message_templates** |
| organizations | 2 | 0001, 0002 | — |
| parties | 7 | 0001, 0003–0007 | 0002_clear_age_with_date_of_birth (data fix) |
| payments | 2 | 0001, 0002 | — |
| pdf | 1 | 0001 | — |
| scrutiny | 5 | 0001, 0003–0005 | **0002_seed_checks_rule** |
| users | 6 | 0001, 0003, 0006 | **0002_seed_registration_otp_template**, **0004_seed_registration_request_types**, **0005_seed_password_reset_otp_template** |

Total: 69 migration files, 12 of them with `RunPython`.

### 2.2 Data migrations, classified

**A. Reference-data seeds → move to `../data/seed`** (the data must exist in every
environment):

| Migration | Model(s) | Rows |
|---|---|---|
| `cms/0002_seed_default_pages` | `cms.PageCategory`, `cms.Page` | categories `help`, `main`, `faq`; pages `terms`, `privacy`, `support` (markdown placeholder content, each in category `main`) |
| `dristi_requests/0002_seed_lawyer_bar_update` | `auth.Group`, `dristi_requests.RequestType`, `dristi_requests.ApprovalStep` | group `BAR_ID_APPROVER`; type `LAWYER_BAR_UPDATE` (schema, `min_documents=1`); step order 0 → `BAR_ID_APPROVER` |
| `users/0004_seed_registration_request_types` | same as above | types `ADVOCATE_REGISTRATION` (`min_documents=1`), `CLERK_REGISTRATION` (`min_documents=0`); one step each → `BAR_ID_APPROVER` |
| `hearings/0002_seed_hearing_purposes` | `hearings.HearingPurpose` | 19 purposes (`code`, `label`, `sequence` = 1-based position) |
| `hearings/0009_seed_hearing_role_groups` | `auth.Group` | `HEARING_CONTROLLER`, `NEXT_HEARING_SETTER`, `ORDER_DATA_FILLER` |
| `messaging/0005_seed_message_templates` | `messaging.MessageTemplate` | 7 SMS templates (`ACCOUNT_LOGIN_OTP_SMS`, `CASE_FILING_SIGNATURE_PENDING_SMS`, `CASE_FILING_MOBILE_VERIFICATION_OTP_SMS`, `CASE_FILING_SCRUTINY_ERRORS_SMS`, `CASE_FILING_SCRUTINY_PASSED_SMS`, `ACCOUNT_REGISTRATION_REJECTED_SMS`, `ACCOUNT_REGISTRATION_APPROVED_SMS`) |
| `users/0002_seed_registration_otp_template` | `messaging.MessageTemplate` | `ACCOUNT_REGISTRATION_OTP_SMS` |
| `users/0005_seed_password_reset_otp_template` | `messaging.MessageTemplate` | `ACCOUNT_PASSWORD_RESET_OTP_SMS` |
| `hearings/0008_seed_hearing_message_templates` | `messaging.MessageTemplate` | `HEARING_SCHEDULED`, `HEARING_RESCHEDULED`, `HEARING_CANCELLED` |
| `scrutiny/0002_seed_checks_rule` | `core.BusinessRule`, `scrutiny.ScrutinyRuleBinding` | rule `SCRUTINY_CHECKS_DEFAULT` (engine `gorules`, ZEN graph built in Python, input and output JSON schemas); national binding `decision=CHECKS`, `organization=NULL` |

**B. One-off data fixes → drop and do not replace.** They only fixed rows that
existed before a rule changed. A fresh database has no such rows, and the models
now enforce the rule.

| Migration | Why it can go |
|---|---|
| `messaging/0004_enforce_uppercase_message_keys` | Uppercases existing keys. The `CheckConstraint`s it adds are already declared in `MessageTemplate.Meta` and `MessageLog.Meta`, so the regenerated `0001_initial` will include them. |
| `parties/0002_clear_age_with_date_of_birth` | Clears `age` where `date_of_birth` is set. `Person.clean_fields` now does this on save. |

## 3. Target layout of `../data/seed` (Phase 2)

`../data/seed/core` already means "reference data every environment needs" and is
loaded with `manage.py seed data/seed/core/`. All category-A data goes there,
grouped by owning app. The command scans the folder recursively (`rglob`) and
orders files by model load order, so subfolders work without changes.

```
data/seed/
├── README.md                          # updated (section 8)
├── core/
│   ├── languages.toml                 # existing
│   ├── auth/
│   │   └── groups.toml                # BAR_ID_APPROVER, HEARING_CONTROLLER,
│   │                                  # NEXT_HEARING_SETTER, ORDER_DATA_FILLER
│   ├── cms/
│   │   ├── page_categories.toml       # help, main, faq
│   │   └── pages.toml                 # terms, privacy, support → categories = ["main"]
│   ├── dristi_requests/
│   │   ├── request_types.toml         # LAWYER_BAR_UPDATE, ADVOCATE_REGISTRATION, CLERK_REGISTRATION
│   │   └── approval_steps.toml        # one step per type, approver_group = "BAR_ID_APPROVER"
│   ├── hearings/
│   │   └── hearing_purposes.toml      # 19 purposes, explicit sequence 1..19
│   ├── messaging/
│   │   ├── account_templates.toml     # login / registration / password-reset OTPs,
│   │   │                              # registration approved / rejected
│   │   ├── case_filing_templates.toml # CASE_FILING_* templates
│   │   └── hearing_templates.toml     # HEARING_SCHEDULED / RESCHEDULED / CANCELLED
│   └── scrutiny/
│       ├── business_rules.toml        # SCRUTINY_CHECKS_DEFAULT
│       └── rule_bindings.toml         # CHECKS → SCRUTINY_CHECKS_DEFAULT (national)
└── example/                           # unchanged (test + format example)
```

Notes on the data files:

- Copy values **exactly** from the migrations, including the ` - On Courts`
  suffixes, `priority`, `category` and `max_retries` (OTP templates: `OTP` / `1`;
  notification templates: `NOTIFICATION` / `0`), `subject = ""`, and
  `is_active = true` on request types.
- JSON-field values (`data_schema`, `schema`, `condition`,
  `rule_input_schema`, `rule_output_schema`) are written as TOML tables or
  inline tables. `JSONField.to_python` keeps them as they are. TOML has no
  `null`; none of the current values need it (`"type": ["string", "null"]` is a
  string array and is fine).
- `rule_expression` is a `TextField` that holds JSON. Write it as a TOML
  multi-line literal string (`'''{ ... }'''`) with the exact JSON that
  `json.dumps(GRAPH, ensure_ascii=False)` produces in
  `scrutiny/0002_seed_checks_rule.py`. Generate the JSON once by running that
  module's `GRAPH`. Do not type it by hand. (A TOML table would not work: the
  command stringifies tables with `str()`, which is not JSON.)
- Use the same `[seed]` / `[[rows]]` format as the existing files, with a short
  header comment that names the spec section the data comes from (as the
  migrations do now).

## 4. Changes needed in the seeding engine (Phase 1)

The command currently registers only `locations.Location`,
`organizations.Organization`, `core.BusinessRule`, `core.Configuration`,
`core.PublicConfiguration`, `cms.PageCategory`, `cms.Page`, `core.Language`.

### 4.1 New `SeedSpec`s (`../src/apps/core/seeding/specs.py`)

| Model | Natural key | Fields | FK / M2M by code | Order |
|---|---|---|---|---|
| `auth.Group` | `name` | `name` | — | 5 |
| `messaging.MessageTemplate` | `message_key`, `message_type` | `message_key`, `message_type`, `subject`, `content`, `data_schema`, `priority`, `category`, `max_retries`, `provider_template_id`, `is_active` | — | 30 |
| `hearings.HearingPurpose` | `code` | `code`, `label`, `description`, `sequence`, `is_active` | — | 30 |
| `dristi_requests.RequestType` | `code` | `code`, `name`, `description`, `schema`, `min_documents`, `is_active` | — | 30 |
| `dristi_requests.ApprovalStep` | `request_type`, `order` | `order`, `approver_role`, `condition` | `request_type` → `RequestType.code`; `approver_group` → `auth.Group.name` | 60 |
| `scrutiny.ScrutinyRuleBinding` | `decision`, `organization` | `decision`, `rule_code`, `note`, `is_active` | `organization` → `Organization.code` (nullable) | 60 |

(`core.BusinessRule` is already registered at order 30. The binding must load
after it because `ScrutinyRuleBinding` holds the rule only as a `rule_code`
string, but the rule should exist first.)

The registry keeps its "specs carry no logic" rule. `specs.py` already refers to
models by label, so no `apps.core → apps.<other>` import cycle is introduced.

### 4.2 Command changes (`seed.py`)

1. **Foreign keys inside the natural key.** `_seed_row` checks whether a row
   exists with `filter(**{name: row[name]})`. For `ApprovalStep` that becomes
   `request_type="LAWYER_BAR_UPDATE"`, which is wrong. Change the existence
   lookup so that a key field also listed in `fk_by_code` is matched as
   `<name>__<ref.key>` (for example `request_type__code`). Make the same change
   to the post-`clean()` existence lookup.
2. **Nullable FK in the natural key.** The national scrutiny binding has
   `organization = NULL`. Today, an empty key field skips the row
   ("missing key field"). Allow an empty value for a key field that is a
   nullable FK, and match it with `<name>__isnull=True`. Other key fields still
   reject empty values.
   *Alternative (no command change):* use key `("decision", "rule_code")` for
   bindings. This is simpler, but it would wrongly treat a state binding that
   reuses the national rule code as "already exists". Not recommended.
3. Add tests to `apps/core/tests/test_seed.py` for both cases: an FK in the key,
   a null FK in the key, and re-running as a no-op.

No other engine change is needed. Group, template, purpose and request-type
rows are plain scalar or JSON fields.

### 4.3 Behaviour differences to accept

- Most of the migrations used `update_or_create` (upsert). The `seed` command
  only inserts (spec 0025 §5). Once a row exists, changing it in TOML does not
  update the database. Changes are made in the admin. This is the intended
  spec 0025 behaviour, but it is a change for message templates and request
  types.
- Rows now go through `full_clean()`. The migrations bypassed it because they
  used historical models. Expect validation of `BusinessRule` (engine
  available, code format, schema/expression agreement), `MessageTemplate.clean`,
  and `ScrutinyRuleBinding.clean`. Run `seed --dry-run --strict` while porting
  the data so any row that fails validation shows up before anything is saved.
- Reverse (`unseed`) functions go away. Seeded data is removed in the admin, as
  spec 0025 says.

## 5. Regenerating migrations (Phase 2)

Do this on a dedicated branch, after the seed data from sections 3–4 is in place
and its tests pass.

1. Confirm the starting point: `cd src && python manage.py makemigrations --check --dry-run`
   reports **No changes detected**.
2. Delete every generated migration and keep the packages:
   `find src/apps -path '*/migrations/0*.py' -delete`, plus the
   `__pycache__` directories under `migrations/`. Keep each
   `migrations/__init__.py`. 
3. Regenerate: `cd src && python manage.py makemigrations` (all apps at once, so
   Django resolves cross-app dependencies such as
   `users ↔ dristi_requests ↔ auth`, `hearings → messaging/cases/organizations`,
   `scrutiny → core/cases`, `payments → cases`).
   - Django may split an app into `0001_initial` + `0002_initial` to break a
     circular foreign key. That is expected; accept it and do not hand-edit.
4. Check the output:
   - No `RunPython` / `RunSQL` anywhere:
     `grep -rlE "RunPython|RunSQL" src/apps/*/migrations` returns nothing.
   - `makemigrations --check --dry-run` → No changes detected.
   - `python manage.py migrate` on an **empty PostgreSQL** database (compose
     `db` service) and on SQLite (test settings) both succeed.
   - Review the generated SQL with `sqlmigrate` for the models with special
     constraints, to confirm they survive: `MessageTemplate` / `MessageLog`
     (`*_message_key_upper_snake` check constraints, `unique_message_key_type`),
     `ScrutinyRuleBinding` (conditional unique constraints), `hearings`
     (multiple `UniqueConstraint`s), `core` (`Configuration`,
     `PublicConfiguration`, `Language` constraints), and the `simple_history`
     historical tables.
   - `python manage.py check`.
5. Run `ruff check . && ruff format .` (the migrations are generated code, but
   they are still linted and formatted).

## 6. Test changes (Phase 2)

Phase 1 adds only engine tests in `apps/core/tests/test_seed.py` (section 9.1).
Everything below belongs to Phase 2.

Many tests assume data that migrations used to insert. With pytest-django, that
data was present in the test database for every test. After the cleanup it is
not, so seed the same data once per test session:

- Add `src/conftest.py` that overrides `django_db_setup` so that, after the test
  DB is created, it runs `call_command("seed", <BASE_DIR.parent>/data/seed/core, "--strict")`
  inside `django_db_blocker.unblock()`. This gives every test the same starting
  data the migrations gave, and `--strict` makes the test session fail if the
  core seed data does not load cleanly.
  - No test uses `TransactionTestCase` / `transactional_db` /
    `serialized_rollback` today, so session-level data is not flushed. If one is
    added later, it will need `serialized_rollback=True` or its own seeding.
  - Global seeding also loads `languages.toml`. The `languages` fixture in
    `apps/core/tests/conftest.py` becomes a harmless no-op (insert-only). Keep it
    or remove it. Then run the whole suite and confirm that no test outside
    `core` relies on having **no** languages.
- Tests that rely on seeded rows and must keep passing unchanged:
  `apps/dristi_requests/tests/conftest.py` (`LAWYER_BAR_UPDATE`,
  `BAR_ID_APPROVER`), `apps/users/tests/test_verification.py`,
  `test_rejection.py`, `test_otp.py`, `apps/hearings/tests/test_admin.py`,
  `test_models.py`, `test_listing.py`, `apps/scrutiny/tests/test_checks.py`
  (`SCRUTINY_CHECKS_DEFAULT` and its national binding), `apps/cms/tests/test_models.py`.
- Update wording that mentions migrations:
  - `apps/cms/tests/test_models.py::TestSeedData` docstring ("The seed migration…").
  - `apps/dristi_requests/tests/test_models.py:131` docstring ("data migration").
  - `addon/cdac_sms_gateway/tests/test_delivery.py:37` comment ("seeded by migration 0005").
- New tests:
  - `seed data/seed/core/ --strict` on an empty DB creates the expected counts
    (templates 12, purposes 19, request types 3, approval steps 3, groups 4,
    1 business rule + 1 binding, 3 categories + 3 pages, 3 languages), and a
    second run creates 0 rows.
  - The seeded `SCRUTINY_CHECKS_DEFAULT` `rule_expression` produces the same
    results as before on the existing samples. `test_checks.py` already does this
    once the rule comes from the seed.
  - Optional guard: a test that fails if any file under `src/apps/*/migrations/`
    contains `RunPython`, so new reference data goes into `../data/seed`.

## 7. Rollout for developers and shared environments (Phase 2)

Every existing database has a migration history that no longer matches the
files. After merging:

1. Docker: `docker compose -f docker/docker-compose.yml down -v` (drops the
   `postgres_data` volume), then `up -d --build`, then
   `exec web python manage.py seed /data/seed/core/`.
2. Local (non-Docker): drop and recreate the database, run `python manage.py migrate`,
   then `python manage.py seed ../data/seed/core/`.
3. Reload environment-specific data afterwards (states/districts/pincodes from
   `dristi-be-experiments`, any `example/` data in use). Admin users have to be
   created again.

**Decision needed — automatic seeding on startup.** OTP login, registration
approval and hearing notifications now depend on seeded rows instead of
`migrate`. Options:

- (a) Add a `seed /data/seed/core/` step to `../docker/entrypoint.sh` right after
  `run_migrations`. This is safe because seeding only inserts and is idempotent.
  **Recommended.**
- (b) Keep seeding manual and only document it (the current situation for
  languages).

## 8. Documentation updates

The `../data/seed/README.md` engine notes and the spec 0025 update ship in
Phase 1. Everything else here is Phase 2.

- `../data/seed/README.md`: list everything under `core/` and the new seedable
  models, and explain FK-in-key and nullable-key behaviour.
- `../docs/development.md`: the "Seeding initial data" and setup steps already say
  `migrate` then `seed .../core/`. Update the list of what `core/` contains and
  add the database-reset note.
- `0025-data-seeding-command.md`: add the new registered models and the
  natural-key extensions (section 4.2).
- `../AGENTS.md`: add a rule, "Reference data goes in `data/seed/` TOML and is
  loaded by `manage.py seed`; do not write data migrations," with a pointer to
  `data/seed/README.md`.
- Comments in code that name the data migrations, for example the `ports.py`
  note in `hearings/0009` ("removed with `ports.py` once court roles are held
  per courtroom"). Move this note next to the groups in `groups.toml`.

## 9. Phases

### 9.1 Phase 1 — update the seed engine

**Goal:** `manage.py seed` can load every model and row shape that the data
migrations insert today. At the end of this phase, the engine is ready, but no
reference data has moved yet.

**In scope**

1. Command changes in `../src/apps/core/management/commands/seed.py`
   (section 4.2):
   - FK fields inside the natural key are matched by the related row's code
     (`<name>__<ref.key>`), both in the existence check and in the
     post-`clean()` check.
   - A nullable FK key field may be empty and is then matched with
     `<name>__isnull=True`. Other empty key fields are still rejected.
2. New `SeedSpec`s in `../src/apps/core/seeding/specs.py` (section 4.1):
   `auth.Group`, `messaging.MessageTemplate`, `hearings.HearingPurpose`,
   `dristi_requests.RequestType`, `dristi_requests.ApprovalStep`,
   `scrutiny.ScrutinyRuleBinding`, with the load orders from section 4.1.
3. Tests in `../src/apps/core/tests/test_seed.py`. Use inline TOML written to
   `tmp_path`, the same way the existing tests do:
   - `seed --list` shows the new models in load order.
   - For each new spec: a row is created when the table is empty, a second run
     leaves it unchanged, and an existing row is not modified.
   - `ApprovalStep`: the key `(request_type, order)` is resolved by the request
     type's code, and its `approver_group` is resolved by the group's name.
   - `ScrutinyRuleBinding`: the national binding (no `organization`) is
     created once and is unchanged on a second run. An organization-scoped
     binding with the same `decision` is a separate row.
   - An unresolved FK in the key skips the row. `--strict` then rolls back.
   - `MessageTemplate` / `BusinessRule` rows that fail `full_clean()` are
     skipped with a readable message.
   - Composite key `(message_key, message_type)` for templates.
   - **Collision note:** while the old migrations still exist, the test database
     already contains their rows (for example `LAWYER_BAR_UPDATE`,
     `HEARING_SCHEDULED`, `BAR_ID_APPROVER`). Phase 1 tests must use their own
     codes (for example `TEST_*`), or assert that these existing rows are
     reported as *unchanged*.
4. Engine documentation only:
   - `../data/seed/README.md`: list the new seedable models, with a short TOML
     example for an FK-in-key row (`ApprovalStep`) and a nullable-key row
     (national `ScrutinyRuleBinding`). Explain how JSON fields and a JSON
     `rule_expression` (multi-line literal string) are written.
   - `0025-data-seeding-command.md`: add the new registered models and the
     natural-key extensions.

**Out of scope for Phase 1:** new files under `../data/seed/core`, any change to
`src/apps/*/migrations/`, `src/conftest.py`, existing tests in other apps,
`docker/entrypoint.sh`, `AGENTS.md`, and `docs/development.md`.

**Done when**

- `seed --list` shows all 14 seedable models.
- The new tests pass, and the full suite passes unchanged on SQLite and on
  PostgreSQL (CI).
- `ruff check . && ruff format .` and `python manage.py check` are clean.
- `makemigrations --check --dry-run` still reports no changes. Phase 1 adds no
  model change.


### 9.2 Phase 2 — move the data and reset migrations

**Goal:** reference data lives only in `../data/seed/core`. Migrations are
regenerated from scratch, with no `RunPython`.

**Depends on:** Phase 1

1. **Data files.** Add the TOML files under `../data/seed/core` (section 3).
   Copy values exactly from the data migrations. Generate the scrutiny
   `rule_expression` JSON from the migration's `GRAPH`. Run
   `seed --dry-run --strict data/seed/core/` against a fresh database. Add the
   core-seed test: the expected row counts on the first run, and 0 created on a
   second run (section 6).
2. **Test seeding.** Add `src/conftest.py` with the session-level
   `django_db_setup` seeding, and fix the test wording that mentions migrations
   (section 6). The suite must pass while the old migrations **still exist**.
   Because seeding only inserts, this proves the TOML matches what the
   migrations insert.
3. **Migration reset.** Delete and regenerate the migrations, remove
   `src/apps/notifications/`, and verify everything on PostgreSQL and SQLite
   (section 5). Optionally add the guard test that rejects `RunPython`.
4. **Startup seeding.** Change `../docker/entrypoint.sh` if option (a) from
   section 7 is chosen.
5. **Documentation.** Update `../docs/development.md` and `AGENTS.md`, add the
   reset note, and move the `ports.py` note next to the groups in `groups.toml`
   (sections 7–8).
6. **Rollout.** Announce the database reset to the team, and reset the shared
   dev databases (section 7).

**Done when**

- No migration contains `RunPython` or `RunSQL`.
- `migrate` followed by `seed data/seed/core/` on an empty database gives the
  same reference data the old migrations gave.
- The full suite, `ruff`, `check` and `makemigrations --check` are clean.


## 10. Open questions

1. Should the CMS placeholder pages (`terms`, `privacy`, `support` with dummy
   markdown) be in `core/` (every environment) or `example/`? The plan keeps
   them in `core/` because the migration seeds them everywhere today.
2. Should seeding run automatically on startup (section 7, option a) or stay a
   manual step?
3. Should the Python builder for the scrutiny ZEN graph (`CHECKS`, `_alert`,
   `_per_cheque` in `scrutiny/0002`) be kept as a small developer script to
   regenerate the JSON, or should the TOML JSON be the only source from now on
   (edited in TOML or the admin)?
4. Should `auth.Group` stay seedable through the generic engine, or wait for the
   per-courtroom roles work (spec 0026) to replace the placeholder hearing
   groups?
