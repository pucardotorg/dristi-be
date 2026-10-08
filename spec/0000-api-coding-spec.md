# Dristi API Coding Specification

> This document defines the required standards for designing and implementing REST APIs in Dristi.

## Project Decisions (Locked)

1. **No Pydantic API resource layer** for request/response handling.
   - DRF serializers are the single source of truth for API validation and schema.
2. **Reusable API base classes are DRF-native**.
   - Use the project’s shared DRF base viewsets as the default foundation for CRUD-style APIs.
3. **Swagger/OpenAPI is required** via `drf-spectacular`.
   - Schema endpoint: `/api/schema/`
   - Swagger UI endpoint: `/api/docs/`
4. **Every API JSON response must include a `meta` object**.
   - `timestamp`: current time in IST (`Asia/Kolkata`) ISO-8601 format with timezone
   - `app_version`: `GIT_COMMIT_SHA` from settings
   - `spec_version`: fixed value `"1.0"`
5. **Endpoints must be tagged in Swagger by owning app/domain by default**.
   - Example: health/liveness endpoints owned by core use `core`; user endpoints use `users`.
6. **Every API error response uses one shape**: an `errors` array of
   `{"code", "msg", "field"?}` items plus the usual `meta` (section 9).
   - `code` is a registered, stable `E<domain><seq>` identifier (for example `E01001`).
   - The full code catalogue is published in the Swagger documentation (section 10).

## Quick-start API Template

Use this as the default workflow for adding a new API endpoint group in any domain app:

1. **Model**: define or update domain model(s) and constraints.
2. **Serializer**: add DRF serializer(s) with explicit fields and read-only server fields.
3. **View/ViewSet**: use shared DRF base viewsets by default; keep view logic thin.
4. **Routing**: register endpoints in the domain app `urls.py` and include under `/api/v1/`.
5. **Swagger**: add/confirm schema annotations and set default app/domain tags.
6. **Errors**: define the domain's business error codes in `errors.py` (section 9.4), raise them, and list them on the endpoint with `error_responses()` (section 10.1); never hand-build an error `Response`.
7. **Tests**: cover success path, auth/permissions, response shape (including `meta`), error codes, and pagination where relevant.
8. **Quality checks**: run pytest, Ruff (check + format), and Django system checks.

Starter conventions:

- Prefer read-only viewsets for list/retrieve-only APIs.
- Use named routes and `reverse()` in tests.
- Keep business logic in models/services/tasks, not serializers/views.

## 1. Architecture Overview

Dristi APIs use Django REST Framework (DRF) with this general layering:

1. **Models** — database schema and constraints.
2. **Services / Tasks** — domain/business logic and async workflows.
3. **Serializers** — request validation, response shape, and OpenAPI schema.
4. **Views / ViewSets** — endpoint behavior and orchestration.
5. **URL Routing** — versioned API path exposure.
6. **Schema/Docs** — OpenAPI generation and Swagger UI.

Keep views thin. Put business rules in models, services, or tasks.

## 2. Directory Structure Standard

For a new API domain app (for example `cases`), prefer:

```text
apps/<domain>/
├── __init__.py
├── apps.py
├── models.py
├── serializers.py
├── views.py
├── urls.py
├── errors.py                 # domain error codes (section 9.4), when the app has any
├── tasks.py                  # optional
├── admin.py
├── migrations/
└── tests/
    ├── __init__.py
    └── test_api.py
```

Register each app in settings using its full dotted app path.

## 3. Model Standards

### 3.1 Base classes

Prefer shared base classes for common fields and behavior:

- UUID primary key and timestamps
- Optional activation state support
- Optional structured extension attributes

Most domain models should inherit the common base model unless there is a clear reason not to.

### 3.2 General rules

- Use explicit constraints (`UniqueConstraint`, `CheckConstraint`) where practical.
- Use `TextChoices` for bounded enums.
- Validate invariants in `clean()`/`full_clean()` when model-level correctness matters.
- Set `Meta.ordering` explicitly for predictable list behavior.

## 4. Serializer Standards

Use DRF serializers (typically `ModelSerializer`) per domain app.

Rules:

- Declare explicit `fields`; do not use `"__all__"`.
- Mark server-managed fields as `read_only_fields`.
- Keep serializer validation focused on payload correctness.
- Move complex business logic to services/models.

## 5. View and ViewSet Standards

Use shared DRF-native base viewsets for model-backed APIs by default.

Rules:

- Use read-only base viewsets for list/retrieve-only resources.
- Use full CRUD base viewsets only when create/update/delete are required.
- Use function-based `@api_view` only for lightweight utility endpoints.
- Keep permission/authentication behavior explicit.
- Use DRF `Response` and `status.HTTP_*` constants.
- Keep domain decisions out of view code when possible.

## 6. Authentication and Permission Standards

Baseline defaults:

- `SessionAuthentication`
- `TokenAuthentication` 
- `IsAuthenticated`
- `IsAuthenticatedAndRegistered` (`apps.users.services.permissions`)

Implications:

- **Nothing is readable by default.** An endpoint that declares no
  `permission_classes` requires an authenticated account that has finished
  registration.
- Public endpoints must explicitly declare `AllowAny`.
- Endpoints reachable part-way through registration — the wizard's own steps —
  declare `IsAuthenticated` alone.

### 6.1 Why registration completeness is part of the default

An account can exist and authenticate before its registration is finished —
`POST /users/` issues a session cookie mid-wizard so the flow is resumable
(spec 0005 section 2.3). Without `IsAuthenticatedAndRegistered` in the baseline,
every endpoint would have to remember that half-registered sessions exist. The
gate is checked once, centrally, and the wizard's own endpoints opt out.

It is a separate class from `IsAuthenticated` rather than a combined check
because the two failures need different remedies: not logged in means log in,
incomplete registration means finish the wizard.

## 7. URL Routing and Versioning Standards

- Each app owns its own `urls.py`.
- API URLs are mounted under `/api/`.
- Endpoints are versioned via path segment (currently `/api/v1/`).
- Domain routes should be included into the versioned API namespace.
- Keep route names stable for reverse resolution and client integrations.

## 8. Response Envelope Metadata Standard

Every API JSON response must include:

```json
{
  "meta": {
    "timestamp": "2026-09-16T12:34:56.123456+05:30",
    "app_version": "abc123def",
    "spec_version": "1.0"
  }
}
```

Implementation behavior:

- Object responses: append `meta` at top level.
- Array/scalar responses: wrap as `{ "data": ..., "meta": ... }`.
- Paginated responses: keep pagination keys and add top-level `meta`.
- Error responses: `{ "errors": [...], "meta": ... }` (section 9).
- Non-JSON documentation responses are excluded from this rule.

## 9. Error Handling and Validation Standards

### 9.1 Error response shape

Every error response — validation, business rule, authentication, permission,
not-found, throttling — has the same body:

```json
{
  "errors": [
    { "code": "E01001", "msg": "Invalid or expired code." },
    { "code": "E00002", "msg": "This field is required.", "field": "mobile_number" }
  ],
  "meta": {
    "timestamp": "2026-09-16T12:34:56.123456+05:30",
    "app_version": "abc123def",
    "spec_version": "1.0"
  }
}
```

| Key | Always present | Meaning |
| --- | --- | --- |
| `errors` | yes | Non-empty array. One item per problem; a request can fail several ways at once. |
| `errors[].code` | yes | Registered error code (9.2). **Clients branch on this.** |
| `errors[].msg` | yes | Human-readable message. For display and logs only; it may vary, e.g. to name the offending value. |
| `errors[].field` | no | Request field the error refers to. Absent when the error concerns the request as a whole. |
| `meta` | yes | As in section 8. |

`field` is a path into the request body: nested objects are dotted
(`profile.bar_registration_id`) and list elements are indexed
(`documents[0]`, `datapoints[2].version`). DRF's `non_field_errors` are
reported without a `field`.

The HTTP status still carries the error category (400, 401, 403, 404, 409, 413,
429 …); `code` gives the precise reason within it. Headers DRF adds, such as
`Retry-After` and `WWW-Authenticate`, are preserved.

### 9.2 Error codes

Codes have the form `E` + two-digit **domain** + three-digit **sequence**, for
example `E01001`.

| Domain | Owner | Codes |
| --- | --- | --- |
| `00` | common (`apps.api.errors`) | `E00001`–`E00099` field validation; `E00100`–`E00199` request-level (auth, permission, not found, throttling …) |
| `01` | `apps.users` | registration and login |
| `02` | `apps.dristi_requests` | request and approval workflow |

Rules:

- A code, once released, **never changes meaning** and is never reused. Retire
  a code by leaving it unused, not by renumbering.
- A new domain prefix is allocated in `apps.api.errors.DOMAINS` (and in the
  table above) before its first code is defined.
- Codes are registered with `apps.api.errors.define()`. Malformed codes,
  unallocated prefixes and duplicates raise `ImproperlyConfigured` at startup.
- Each code has a default message and HTTP status. The status in the response
  is the exception's own; keep the two in agreement by deriving one from the
  other (9.4).

### 9.3 Validation errors

Use `serializer.is_valid(raise_exception=True)` for serializer-driven flows.

DRF's built-in validation codes are mapped to common codes automatically, so
plain field validation needs no extra wiring:

| DRF code | Error code |
| --- | --- |
| `invalid` | `E00001` |
| `required` | `E00002` |
| `null` | `E00003` |
| `blank` | `E00004` |
| `invalid_choice` | `E00005` |
| `max_length` / `min_length` | `E00006` / `E00007` |
| `max_value` / `min_value` | `E00008` / `E00009` |
| `unique` | `E00010` |
| `does_not_exist` | `E00011` |
| `incorrect_type`, `not_a_list`, `not_a_dict` | `E00012` |
| `empty` | `E00013` |
| `max_digits`, `max_decimal_places`, `max_whole_digits` | `E00014` |

A validation failure that encodes a **business rule** — "email already taken",
"terms must be accepted" — gets its own domain code. Inside serializer
validation, raise it with `ErrorCode.validation_error()`, which returns a DRF
`ValidationError` carrying the code:

```python
from apps.users import errors


def validate_email(self, value):
    if taken:
        raise errors.EMAIL_TAKEN.validation_error()  # field: "email"


def validate(self, attrs):
    raise errors.PASSWORD_REJECTED.validation_error({"password": messages})
```

Use this rather than `BusinessError` inside serializers: DRF only collects
`ValidationError` there, and only then attributes it to the field being
validated.

Django's `ValidationError` — raised by model validators, `full_clean()`, or
models that validate in `save()` such as `BaseExtendableModel` — is translated
to a 400 with its field keys and codes kept, instead of DRF's default 500.

An error whose code is neither registered nor a DRF built-in falls back to the
common code for its HTTP status (400 → `E00001`, 403 → `E00104`, …), so every
response carries a registered code even if a raise site was missed.

### 9.4 Business errors

Each domain app declares its codes in `<app>/errors.py`:

```python
# apps/users/errors.py
from apps.api.errors import define

OTP_INVALID = define("E01001", "Invalid or expired code.", status=401)
```

From views and services, raise them with `BusinessError`, which takes its
status and code from the definition:

```python
from apps.api.errors import BusinessError
from . import errors

raise BusinessError(errors.OTP_INVALID)
raise BusinessError(errors.OTP_INVALID, "Code expired 3 minutes ago.")  # custom msg
raise BusinessError(errors.EMAIL_TAKEN, field="email")  # field-level
```

Domain exception classes that subclass DRF exceptions (for example
`InvalidRequestStateError(ValidationError)`) remain fine; set their
`default_code` (and, where they set one, `status_code`) from the registered
code. A test checks every such class's status against its registered status:

```python
class ApprovalRoutingError(APIException):
    status_code = errors.APPROVAL_ROUTING.status
    default_detail = errors.APPROVAL_ROUTING.msg
    default_code = errors.APPROVAL_ROUTING.code
```

Permission classes report their code through DRF's `code` attribute:

```python
class IsAuthenticatedAndRegistered(BasePermission):
    message = errors.REGISTRATION_INCOMPLETE.msg
    code = errors.REGISTRATION_INCOMPLETE.code
```

Do **not** return a hand-built error `Response` (`Response({"detail": ...}, status=401)`).
It bypasses the exception handler, so it neither has the standard shape nor
rolls back the transaction.

### 9.5 Implementation

- `REST_FRAMEWORK["EXCEPTION_HANDLER"]` is `apps.api.errors.api_exception_handler`.
  It translates Django's `Http404`, `PermissionDenied` and `ValidationError`
  into their DRF equivalents, delegates to DRF's handler for status, headers
  and transaction rollback, then replaces the body with the `errors` array.
  `MetaJSONRenderer` adds `meta`. `errors` is never empty.
- `ApiConfig.ready()` imports every installed app's `errors` module, so the
  catalogue is complete before the first request or schema build.
- Requests that never reach a DRF view use Django's `handler404` /
  `handler500`, set in `config.urls` to `apps.api.errors.handler404` /
  `handler500`. Under `/api/` they return the standard shape: an unmatched
  route is `E00105`, an unhandled exception is `E00100` with a generic
  message (Django logs the exception first; its details never reach the
  client). Other paths keep Django's pages. Neither handler runs while
  `DEBUG` is on, when Django shows its technical pages instead.
- The shared `upsert` action reports every failing datapoint in one `errors`
  array, with `field` prefixed `datapoints[<index>]`, and rolls back the
  batch. An unknown lookup value is `E00105` on that datapoint.

## 10. Swagger / OpenAPI Standards

`drf-spectacular` is mandatory for schema generation.

Rules:

- Maintain working `/api/schema/` and `/api/docs/` endpoints.
- Add explicit schema annotations for custom actions and function-based endpoints.
- Tag operations by owning app/domain by default.
- Ensure schema reflects auth/permission expectations and response shapes.

### 10.1 Error documentation

The postprocessing hook `apps.api.schema.error_schema_hook` (configured in
`SPECTACULAR_SETTINGS["POSTPROCESSING_HOOKS"]`) makes errors part of the
published documentation automatically:

- `ErrorItem` and `ErrorResponse` component schemas; `ErrorItem.code` is an
  enum of every registered code.
- A `4XX` response referencing `ErrorResponse` on every operation.
- The **error code catalogue** — code, HTTP status, domain and default
  message — appended to the API description shown at the top of `/api/docs/`.

New codes appear in the catalogue as soon as they are defined; there is no
separate list to maintain.

When an endpoint can return specific business errors, list them with
`error_responses()`. It files each code under its own registered status, so
the documented status cannot drift from the returned one; the hook attaches
the `ErrorResponse` body:

```python
from apps.api.schema import error_responses

@extend_schema(
    responses={
        201: ACCOUNT_STATE_RESPONSE,
        **error_responses(errors.OTP_INVALID, errors.ACCOUNT_ALREADY_REGISTERED),
    },
)
```

Tip: use `?format=json` for schema assertions in tests/tooling where JSON is required.

## 11. Pagination Standards

Use DRF page-number pagination as default project behavior.

Rules:

- List endpoints should use standard paginated response shape unless there is a justified exception.
- Keep page size consistent across endpoints unless domain requirements demand otherwise.

## 12. Background Job Standards

When endpoints require asynchronous work:

- Define actors in the owning app’s tasks module.
- Enqueue from views/services.
- Keep actors idempotent and transactional where possible.
- Persist job/delivery state when operational visibility is important.

## 13. API Testing Standards

Use DRF API test utilities and named URL reversing.

Required coverage for each endpoint group:

- Success cases
- Permission/authentication behavior
- Response shape (including `meta`)
- Validation/error behavior where applicable, asserting the error `code`
  (and `field` for field errors) rather than the message text
- Pagination behavior for list endpoints

## 14. Implementation Checklist for New Endpoints

1. Add or update models.
2. Add serializers with explicit fields.
3. Add views/viewsets using shared base classes where applicable.
4. Register routes in app-level URLs and include under versioned API.
5. Define business error codes in the app's `errors.py`; raise them, and document them with `error_responses()`.
6. Add endpoint tests in the owning app.
7. Add/update Swagger annotations and tags.
8. Run quality checks:

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

## 15. Ownership and Consistency Principles

- API behavior should be owned by the domain app that owns the data and business rules.
- Avoid centralizing unrelated domain endpoints in a generic API app.
- Keep route contracts stable while allowing implementation relocation.
- Prefer app-scoped serializers/views/tests to improve maintainability and discoverability.
