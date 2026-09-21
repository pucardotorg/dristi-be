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

## Quick-start API Template

Use this as the default workflow for adding a new API endpoint group in any domain app:

1. **Model**: define or update domain model(s) and constraints.
2. **Serializer**: add DRF serializer(s) with explicit fields and read-only server fields.
3. **View/ViewSet**: use shared DRF base viewsets by default; keep view logic thin.
4. **Routing**: register endpoints in the domain app `urls.py` and include under `/api/v1/`.
5. **Swagger**: add/confirm schema annotations and set default app/domain tags.
6. **Tests**: cover success path, auth/permissions, response shape (including `meta`), and pagination where relevant.
7. **Quality checks**: run pytest, Ruff (check + format), and Django system checks.

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
- Non-JSON documentation responses are excluded from this rule.

## 9. Error Handling and Validation Standards

- Use `serializer.is_valid(raise_exception=True)` for serializer-driven flows.
- Use DRF exceptions and consistent status codes.
- Keep error response shapes stable and predictable.

## 10. Swagger / OpenAPI Standards

`drf-spectacular` is mandatory for schema generation.

Rules:

- Maintain working `/api/schema/` and `/api/docs/` endpoints.
- Add explicit schema annotations for custom actions and function-based endpoints.
- Tag operations by owning app/domain by default.
- Ensure schema reflects auth/permission expectations and response shapes.

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
- Validation/error behavior where applicable
- Pagination behavior for list endpoints

## 14. Implementation Checklist for New Endpoints

1. Add or update models.
2. Add serializers with explicit fields.
3. Add views/viewsets using shared base classes where applicable.
4. Register routes in app-level URLs and include under versioned API.
5. Add endpoint tests in the owning app.
6. Add/update Swagger annotations and tags.
7. Run quality checks:

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
