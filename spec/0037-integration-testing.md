# 0037 — Integration Testing

## Status

Proposed

## References

- Specs: [`0000`](0000-api-coding-spec.md) §13 (API testing standards) and §15
  (app-scoped tests), [`0011`](0011-case-workflows.md) (the lifecycle flows
  these tests walk), [`0026`](0026-dramatiq-crontab.md) §8 (testing scheduled
  and delayed jobs)
- Exemplar suites this spec generalises:
  `apps/cases/tests/test_filing.py` (multi-API filing flow),
  `apps/scrutiny/tests/test_api.py` (two-actor court workflow),
  `apps/hearings/tests/test_admin.py` (admin actions between service calls),
  `apps/esign/tests/test_integration.py` (initiate → callback → read-back)

> **Scope note.** This spec defines the one way to write an **integration
> test** in Dristi: a test that walks a flow through the system's real
> surfaces — one or more API calls, database state built before those calls,
> and Django admin actions in between — instead of calling a unit in
> isolation. It covers arrangement, execution and assertion style. It does not
> change how endpoints are built (0000) or how jobs are scheduled (0026).

## Context

A unit test calls one function with controlled inputs. Most Dristi behavior is
not like that. The meaningful rules live **between** requests:

- a case is drafted, filled section by section, signed, paid — and only then
  may scrutiny start (`apps/cases/tests/test_filing.py`);
- a hearing is scheduled through the orders contract, started through the
  courtroom service, and then inspected in the admin
  (`apps/hearings/tests/test_admin.py`);
- an eSign transaction is initiated over the API, completed by an
  unauthenticated provider callback, and read back over the API
  (`apps/esign/tests/test_integration.py`).

Every such test needs the same three things, in varying order:

1. **State before the call** — rows in the database, built by earlier API
   calls, by service functions, by factories, or (rarely) by raw ORM writes.
2. **Actors** — a filer, an officer and a registerer are different users with
   different clients; the same endpoint must be hit as each of them.
3. **Out-of-band events** — an admin edits an entity, a payment gateway calls
   back, a Dramatiq job fires, time passes.

Today each suite reinvents this machinery: `client_for` and `error_codes`
exist, slightly different, in at least three conftests; some suites reach
state through services while others write rows directly; admin interaction is
tested in exactly one app. Nothing is written down, so a new flow test copies
whichever suite the author happened to read last.

## Goals

- One documented pattern for each of the three moves: **state before the
  call**, **several API calls in sequence**, and **admin action in the
  middle**.
- A strict preference order for building state (§3) so tests exercise the
  same paths production does and break when the product changes, not when the
  schema does.
- Deterministic tests: pinned business date, in-memory storage, stub broker,
  no real network, no inter-test leakage.
- Tests that stay where the behavior lives (0000 §15): the flow test for a
  transition belongs to the app that owns the transition.

## Non-goals

- End-to-end tests against a running stack (browser, real Postgres, real
  Redis, real SMS/eSign/payment gateways). Those belong to a separate
  environment suite; everything here runs under `config.settings.test`.
- Load, performance or concurrency testing.
- Replacing the per-endpoint coverage required by 0000 §13. Integration tests
  complement it; an endpoint still needs its own success/auth/shape/error
  tests.
- A shared "integration helper" package. The patterns below are small enough
  to copy; a framework is a non-goal (§11, D3).

## 1. What an integration test is

An integration test, for this spec, is any test that does at least one of:

| # | Shape | Example |
| --- | --- | --- |
| 1 | **Several API calls in sequence**, where a later call depends on an earlier one | draft → add participants → add evidence → sign → file |
| 2 | **State built before the API call** — through the service layer, a factory, or a direct write | a filed `Case` built via `services`, then `GET` the scrutiny list |
| 3 | **An admin-dashboard action between calls** | superuser retires a `HearingPurpose` in admin, then the API refuses to schedule with it |
| 4 | **An out-of-band event**: provider callback, Dramatiq message, scheduled job | eSign callback lands, then `GET` shows the signed document |

All four run the full request cycle — routing, authentication, permission
checks, serializers, services, signals — against the test database, through
DRF's `APIClient` (for `/api/v1/`) or Django's test `Client` (for `/admin/`).
Nothing here patches a view, a serializer, or the domain's own services.

## 2. Where integration tests live

Per 0000 §15, tests are app-scoped:

```text
apps/<domain>/tests/
├── __init__.py
├── conftest.py          # fixtures: users, clients, pinned date, storage, caches
├── factories.py         # plain builder functions for domain state
├── test_api.py          # per-endpoint coverage (0000 §13) + reusable step helpers
├── test_admin.py        # admin-surface behavior, when the app exposes admin
└── integration/         # flow tests; auto-marked `integration` (rule 6)
    ├── __init__.py
    └── test_<flow>.py   # one integration module per flow
```

Rules:

1. **The flow test lives in the app that owns the behavior under test.**
   Filing a case lives in `apps.cases`; what scrutiny does with a filed case
   lives in `apps.scrutiny` even though the setup files a case.
2. **One module per flow**, named after it: `test_filing.py`,
   `test_correction.py`, `test_collections_lifecycle.py`. A module docstring
   cites the spec sections it pins:
   `"""Preview, completeness check, status transitions and signing (spec 0021 §6–8)."""`
3. **pytest function style** with `pytestmark = pytest.mark.django_db` at
   module level. Class-based `APITestCase` suites exist in older apps; do not
   add new ones.
4. Fixtures local to the flow go in the module; fixtures reused across the
   app's modules go in the app's `conftest.py`; builders reused across the
   app go in `factories.py`.
5. **Cross-app imports are allowed for setup only**: an integration test in
   `apps.scrutiny` may import `apps.files.tests.factories.make_file` or
   `apps.parties.tests.factories`, exactly as `apps.cases` tests do today.
   Test *helpers* (step functions) are imported only from the same app's
   modules (`from .test_api import put_section, upload`).
6. **Flow modules live in the app's `tests/integration/` package.** They see
   the app's fixtures for free (pytest conftest discovery walks up), and
   import them one level up (`from ..conftest import error_codes`). A root
   `src/conftest.py` marks every test collected under any `integration/`
   package with `pytest.mark.integration`, so `pytest -m integration` and
   `pytest -m "not integration"` select the suites (§14) with no per-file
   `pytestmark` lines. Legacy flow modules at the `tests/` top level
   (`test_filing.py`, `test_integration.py`) migrate when next touched (§13).

## 3. Building state: the setup ladder

When a test needs state before the call, build it at the **highest rung that
can express it**:

```text
1. API calls          — POST/PUT through APIClient, via step helpers
2. Service functions  — apps.<domain>.services / selectors, the same ones views call
3. Test factories     — plain builder functions in tests/factories.py
4. Raw ORM writes     — Model.objects.create(...) directly
```

The rule, stated by `apps/hearings/tests/factories.py` and adopted project-wide:

> State gets built **the way the product builds it**, never by writing rows —
> unless the row is the thing under test.

- **Rung 1 — API calls.** Default when the flow under test includes the
  earlier steps. Filing tests build the case by calling the real endpoints so
  the whole path is exercised once. Keep the steps in named helpers
  (`put_section`, `add_cheque`, `upload`) so the flow reads as a script.
- **Rung 2 — services.** Default when the earlier steps are *another* app's
  behavior. `apps.scrutiny` tests do not replay filing over HTTP; they call
  the filing services to land a case in `SUBMITTED` and test from there.
  Calling a service is not mocking: it is the same code the view calls.
- **Rung 3 — factories.** For reference data and graphs with no service entry
  point: courts, users with roles, configuration. Factories are plain
  functions with an `itertools.count` for unique values
  (`f"+91900000{next(_numbers):04d}"`), not factory_boy.
- **Reference data goes in through the `seed` command** (spec 0025), not
  through factories: that is the path production loads it by, and seeding is
  insert-only, so the test also proves the TOML parses and its natural-key
  references resolve. Seed from a TOML kept next to the suite (for example
  `apps/cms/tests/data/`), with slugs/keys that cannot collide with
  migration-seeded rows, and let the TOML be the single source of truth —
  parse it back with `tomllib` and validate API output against the file
  content (`apps/cms/tests/test_seeded_pages_api.py`). Seed once per module
  from a module-scoped fixture; per §7 it must depend on `django_db_setup`.
- **Rung 4 — raw ORM.** Reserved for state the product has no path to: a row
  abandoned in a non-terminal state by a "crashed worker", a historical row
  with a backdated `created_at`, corrupt/legacy data under migration tests.
  Say why in a comment when you use it.

Two consequences:

- **Never assert on, or set up through, a model's private representation**
  when a public path exists. If the only way to reach a state is rung 4, that
  is usually a missing service — say so in the test or the PR.
- **`refresh_from_db()` is the way back.** After the API call or admin
  action, reload the entity and assert on the database row, not on cached
  Python objects.

### 3.1 State no internal path can produce: external systems

Payment gateways, SMS providers, eSign, object storage are swapped **at the
settings boundary**, never patched mid-flow:

- `config.settings.test` already routes them to fakes
  (`MockESignProvider`, `DummySMSBackend`, mock payments, `StubBroker`,
  in-memory `STORAGES["files"]`).
- A test that needs a *different* fake uses `override_settings(...)` (as the
  CDAC addon suites do), not `mock.patch` of a service.
- `unittest.mock.patch` is allowed only at the true network edge — the
  `requests`/`httpx` call a gateway client makes — when no provider seam
  exists.

## 4. Multi-API flows

### 4.1 One client per actor

```python
@pytest.fixture
def client_for():
    """Return a factory building API clients signed in as a given user."""

    def factory(as_user):
        client = APIClient()
        client.force_authenticate(as_user)
        return client

    return factory
```

A flow with a filer, an officer and a registerer holds **three clients**, one
per user — never one client re-authenticated mid-test. Re-authenticating one
client hides cookie/auth-state leaks and mis-attributes failures.

### 4.2 Steps are named helpers

Each step is a small function returning the raw response, defined once (in
`test_api.py` for the owning app) and imported by the flow modules:

```python
def put_affidavit(client, case_id, affidavit=AFFIDAVIT):
    return client.put(
        reverse("case-affidavit", args=[case_id]), {"affidavit": affidavit}, format="json"
    )
```

- **Named routes + `reverse()`** (0000 quick-start); where a resource has no
  named route, one URL builder (`url(case, "history")`) per module, not
  f-strings scattered through tests.
- Payload fixtures are module-level constants (`CHEQUE_INFO`, `PRAYER`) so a
  field rename fails in one place.
- A helper asserts nothing except its own preconditions; the flow test owns
  the assertions.

### 4.3 The flow reads as arrange → act → assert, once per beat

```python
def test_corrected_case_needs_new_signatures(client, officer_client, case):
    send_back = officer_client.post(url(case, "send-back"), {"flags": [FLAG]}, format="json")
    assert send_back.status_code == 200

    assert put_section(client, case.pk, ...).status_code == 200     # filer corrects
    refreshed = client.get(filer_url(case)).json()
    assert refreshed["signatures"] == []                            # old ones invalidated
```

Each beat asserts both the **response** (status, shape, codes — §8) and the
**state** (`refresh_from_db`, or the next GET). A test that only checks the
last response cannot tell which step failed.

## 5. Driving the Django admin between calls

Admin actions are requests like any other: build a staff/superuser, log the
Django test `Client` in with `force_login`, and POST to the real admin URLs.

```python
@pytest.fixture
def admin_client(client):
    superuser = get_user_model().objects.create_superuser(
        mobile_number="+919000000001", name="admin", email="admin@example.com", password="x"
    )
    client.force_login(superuser)
    return client


def change_url(obj):
    meta = obj._meta
    return reverse(f"admin:{meta.app_label}_{meta.model_name}_change", args=[obj.pk])
```

(`apps/hearings/tests/test_admin.py`.) Rules:

1. **Use the admin for what the admin is for in production**: configuration
   and content an operator edits (purposes, CMS pages, reference data). The
   sequence *superuser edits X in admin → API behavior changes* is the
   contract; testing the API alone misses it.
2. **Go through the real change view POST**, with the full management form
   data the browser would send (`csrf` is off in tests; inline formsets still
   need their `ManagementForm` fields). Do not reach behind the admin and
   flip the field with `Model.objects.update` — that tests nothing about the
   admin's `save_model`, form validation or permissions.
3. **Also assert the admin's own contract** when the app defines one — a
   read-only registry must refuse add/edit/delete with 403 and leave the row
   untouched (`refresh_from_db` after the forbidden POST).
4. The Django `Client` (admin) and DRF `APIClient` (API) coexist fine in one
   test; they are separate objects with separate auth.

## 6. Background jobs, callbacks and time

- **Dramatiq (stub broker)**: messages are not executed in tests. Either
  assert on the enqueued message (queue, actor, options — spec 0026 §8.3), or
  invoke the actor body synchronously via `actor.fn(...)` when the flow needs
  its effects (spec 0026 §8.1). Wrap producers in
  `django_capture_on_commit_callbacks(execute=True)` when they send from
  `transaction.on_commit`.
- **Provider callbacks** are API calls from an unauthenticated client
  (`self.client.force_authenticate(user=None)` then POST the callback URL),
  as in `apps/esign/tests/test_integration.py`.
- **Scheduled jobs** are never run by starting a scheduler; call the service
  with an explicit `now` (spec 0026 §8.1).
- **Business time is pinned, not frozen by library.** Flows that depend on
  "today" set the configuration override in an autouse fixture
  (`business_date` in `apps/hearings/tests/conftest.py`) and compute all
  expectations from that constant. No freezegun/time-machine: the product's
  clock is configuration, so the tests set configuration.

## 7. Determinism and isolation

Every app's `conftest.py` must close the leaks its tests open:

| Leak | Fixture (existing examples) |
| --- | --- |
| Module-scoped seed runs before the test DB exists | the fixture depends on `django_db_setup` as well as `django_db_blocker` — module fixtures are set up before the function-scoped `django_db` marker fixtures, so without it the seed command hits "no such table" when the module runs alone (`apps/cms/tests/conftest.py`) |
| Uploaded files hit disk | `files_storage` → `InMemoryStorage` (`apps/cases`) |
| Draft/session cache carries over | `clear_cache` on the draft alias (`apps/cases`) |
| Query cache hides writes | `no_query_cache` → `cachalot_disabled()` (`apps/hearings`) |
| "Today" drifts | `business_date` pins the override (`apps/hearings`) |
| Settings mutated mid-test | `settings` fixture / `override_settings`, never assignment on the module |

Plus the baseline: `pytest.mark.django_db` (transaction rollback per test),
unique values from `itertools.count` so order-dependence cannot hide, and no
module-level database writes.

## 8. Assertions

Per 0000 §13, extended for flows:

1. **Status first, then shape**: every API response asserts `status_code`;
   success bodies assert the fields the flow depends on and `"meta" in body`.
2. **Errors by code, never message** (0000 §9): each app's conftest provides
   `error_codes(response) -> {field: [code, ...]}` and tests assert
   `(response.status_code, error_codes(response)) == (403, {None: ["E09008"]})`.
3. **State assertions hit the database**: `refresh_from_db()` and check the
   row; for counts/side effects use the ORM (`CaseDocument.objects.filter(...).count()`).
4. **Concurrency contracts stay asserted**: where the API exposes a version,
   the flow re-reads it (`ETag`/`workflow_version`) and sends the stale one
   to prove the conflict path.
5. **One behavior per test.** A flow module is many small tests walking the
   same flow to different depths — not one 200-line test asserting
   everything.

## 9. Template

```python
"""<Flow name> (<spec NNNN> §x–y)."""

import pytest
from django.urls import reverse

from apps.cases.models import Case, CaseStatus

from .conftest import error_codes
from .factories import make_case, make_user

pytestmark = pytest.mark.django_db


def test_<flow>_happy_path(client_for, officer, filer):
    case = make_case(filer, status=CaseStatus.SUBMITTED)     # rung 2/3 setup

    response = client_for(officer).post(reverse("scrutiny-start", args=[case.pk]))
    assert response.status_code == 200
    assert "meta" in response.json()

    case.refresh_from_db()
    assert case.status == CaseStatus.UNDER_SCRUTINY


def test_<flow>_refuses_the_filer(client_for, filer):
    case = make_case(filer, status=CaseStatus.SUBMITTED)
    response = client_for(filer).post(reverse("scrutiny-start", args=[case.pk]))
    assert (response.status_code, error_codes(response)) == (404, {None: ["E00105"]})
```

## 10. Anti-patterns

Tests violating these are changed on review:

1. **Patching the domain's own code** — `mock.patch("apps.cases.services...")`
   in a flow test turns it into a unit test of the wiring. Patch only the
   network edge (§3.1).
2. **Raw ORM writes for state a service produces** (§3) — including
   "updating the entity" between calls with `objects.update()` where the
   product would use an API call, a service or the admin.
3. **`APIClient().force_authenticate` reused across actors** in one test
   (§4.1).
4. **Hand-built admin state** — creating the "operator edited this" state
   with the ORM instead of POSTing the admin form (§5.2).
5. **Sleeping, polling, or starting real workers/schedulers.** The stub
   broker and direct `actor.fn` calls make them unnecessary (§6).
6. **Asserting on error message text, response HTML, or log output** instead
   of codes, rows and bodies.
7. **Cross-flow fixtures** — a fixture that walks half the filing flow so
   "every test starts filed". Compose the named steps inside the test; the
   flow must be visible in the test body.
8. **Tests in a central top-level `integration_tests/` tree.** They rot
   because nothing owns them (0000 §15). The sanctioned separation is the
   per-app `tests/integration/` package (§2 rule 6): physical separation,
   app ownership kept, and the marker machinery follows the location.

## 11. Design decisions

- **D1. pytest functions, not `APITestCase` subclasses.** The dominant
  convention (cases, hearings, scrutiny, notifications) is function style
  with module `pytestmark`; fixtures compose better than class hierarchies
  (`ESignTestCase`-style bases are grandfathered, not extended).
- **D2. Two clients, two surfaces.** `APIClient` for `/api/v1/`, Django
  `Client` for `/admin/`; DRF's client adds nothing to admin form POSTs and
  the Django client keeps auth honest via `force_login`.
- **D3. Patterns over a shared framework.** `client_for` and `error_codes`
  are eight lines each; copying them per app costs less than coupling every
  suite to a shared test package that evolves its own API.
- **D4. The ladder is a rule, not a tip.** "Highest rung that can express the
  state" is enforceable in review and is what keeps a schema refactor from
  rewriting four hundred tests.

## 12. Open questions

1. Should `client_for` / `error_codes` move into `apps.api` as importable
   test utilities (one copy) once a fourth app duplicates them? D3 says no
   for now.
2. ~~A `pytest.mark.integration` marker for selective runs?~~ Resolved:
   yes — location-based, auto-applied by the root `conftest.py` to anything
   collected under a `tests/integration/` package (§2 rule 6, §14).

## 13. Out of scope

- Browser-level E2E, contract tests against real gateway sandboxes, and the
  Docker-level smoke tests run in CI deploy jobs.
- Coverage targets (already governed by `pyproject.toml`,
  `fail_under = 85`).
- Migrating the legacy class-based suites; they are touched only when their
  module is touched anyway.

## 14. Commands

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest apps/<domain>
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest -m integration        # flow suites only
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest -m "not integration"  # unit suites only
cd src && ruff check . && ruff format .
cd src && python manage.py check
```
