# Dristi API Coding Specification

> This document describes the conventions and patterns used to implement REST APIs in the Dristi project.

## Project Decisions (Locked)

1. **No Pydantic API resource layer** for request/response handling.
   - DRF serializers are the single source of truth for API validation and schema.
2. **Reusable API base classes are DRF-native**.
   - Implemented in `src/apps/api/viewsets/base.py`.
   - Use these as the default foundation for new CRUD-style APIs, not a Pydantic resource stack.
3. **Swagger/OpenAPI is required** via `drf-spectacular`.
   - Schema endpoint: `/api/schema/`
   - Swagger UI endpoint: `/api/docs/`
4. **Every API JSON response must include a `meta` object**.
   - `timestamp`: current time in IST (`Asia/Kolkata`) ISO-8601 format with timezone
   - `app_version`: `GIT_COMMIT_SHA` from settings
   - `spec_version`: fixed value `"1.0"`

## 1. Architecture Overview

Dristi APIs are built with Django REST Framework (DRF) and generally follow this flow:

1. **Models** — Django ORM models define database schema and constraints.
2. **Services / Tasks** — domain logic lives in service functions and Dramatiq tasks.
3. **Serializers** — DRF serializers define request validation, response shape, and OpenAPI schema.
4. **Views / ViewSets** — DRF viewsets and API views expose endpoints.
5. **URL routing** — app-level routes are mounted under `/api/` and versioned paths (currently `/api/v1/`).
6. **Schema/Docs** — OpenAPI is served with `drf-spectacular`.

Keep views thin. Put business rules in models, services, or tasks.

## 2. Directory Structure

For a new API domain app (for example `cases`), prefer:

```text
src/apps/cases/
├── __init__.py
├── apps.py
├── models.py
├── serializers.py
├── views.py
├── urls.py
├── tasks.py                  # optional (Dramatiq actors)
├── admin.py
├── migrations/
└── tests/
    ├── __init__.py
    └── test_api.py
```

Register the app in `src/config/settings/base.py` using the full dotted path (`"apps.cases"`).

## 3. Model Conventions

### 3.1 Base classes

Prefer these shared base classes from `apps.core.models`:

- `BaseModel` — UUID primary key (`id`) + `created_at` + `updated_at`
- `BaseActivatableModel` — `is_active` flag + active/inactive queryset helpers
- `BaseExtendableModel` — typed `additional_attributes` JSON extension mechanism

Most domain models should inherit from `BaseModel`.

### 3.2 General guidance

- Use explicit constraints (`UniqueConstraint`, `CheckConstraint`) where practical.
- Use `TextChoices` for bounded enums.
- Validate invariants in `clean()`/`full_clean()` when model-level correctness matters.
- Keep `Meta.ordering` explicit for predictable list behavior.

## 4. Serializer Conventions

Use DRF serializers (typically `ModelSerializer`) in `src/apps/<app>/serializers.py`.

Guidelines:

- Declare explicit `fields`; avoid `"__all__"`.
- Set `read_only_fields` for server-managed fields.
- Keep serializer validation focused on payload validation.
- Put complex business logic in services/models rather than serializer methods.

Example:

```python
class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "username", "is_active", "date_joined"]
        read_only_fields = ["id", "date_joined"]
```

## 5. Views and ViewSets

Dristi provides reusable DRF-native base viewsets in `src/apps/api/viewsets/base.py`:

- `APIModelViewSet` — create/retrieve/update/list/destroy + optional `upsert`
- `APIModelReadOnlyViewSet` — list/retrieve
- Hook methods for extension: `authorize_*`, `validate_data`, `perform_*`, `clean_*`

Prefer these base classes when building new endpoint groups.

Use DRF viewsets where resource semantics map to CRUD. Use function-based `@api_view` endpoints for lightweight utility endpoints.

Current examples:

- `UserViewSet(APIModelReadOnlyViewSet)` in `apps.api.views` for read-only user listing
- `ApiVersionChangeLogViewSet(APIModelReadOnlyViewSet)` in `apps.core.views` for model-backed list/retrieve
- `health_check` (`GET /api/v1/health/`) for liveness

Guidelines:

- Prefer `APIModelViewSet` / `APIModelReadOnlyViewSet` from `apps.api.viewsets.base` for model-backed APIs.
- Use `status.HTTP_*` constants.
- Return DRF `Response` objects.
- Keep authorization explicit with `permission_classes` overrides when needed.

## 6. Authentication and Permissions

Configured defaults (`config/settings/base.py`):

- Authentication:
  - `SessionAuthentication`
  - `TokenAuthentication`
- Permission:
  - `IsAuthenticatedOrReadOnly`

Implications:

- Unauthenticated users can read safe endpoints unless view-level permissions override.
- Unsafe methods generally require authentication.
- Public endpoints should explicitly set `@permission_classes([AllowAny])`.

## 7. URL Routing and Versioning

- App-level router and endpoints live in `src/apps/<app>/urls.py`.
- Project-level mounting is done in `src/config/urls.py`.
- API URLs are mounted under `/api/`.
- Public endpoints should be namespaced by version path segments (currently `v1/`).
- OpenAPI schema is exposed at `/api/schema/`.
- Swagger UI is exposed at `/api/docs/`.

Example (`apps.api.urls`):

```python
router = DefaultRouter()
router.register(r"users", views.UserViewSet, basename="user")

urlpatterns = [
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
    path("v1/", include(router.urls)),
    path("v1/health/", views.health_check, name="health"),
]
```

## 8. Response Envelope Metadata

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

Implementation standard:

- Use `apps.api.renderers.MetaJSONRenderer` as default DRF JSON renderer.
- For object responses, `meta` is appended alongside existing fields.
- For array/scalar responses, payload is wrapped as `{ "data": ..., "meta": ... }`.
- Paginated list responses keep DRF pagination keys (`count`, `next`, `previous`, `results`) and add `meta` at the top level.
- Non-JSON documentation responses (for example Swagger HTML at `/api/docs/`) are outside this JSON envelope rule.

## 9. Error Handling and Validation

- For serializer-based views, use `serializer.is_valid(raise_exception=True)`.
- Use DRF exceptions and status codes consistently.
- Keep response shapes stable for clients.

Typical validation pattern:

```python
serializer = MySerializer(data=request.data)
serializer.is_valid(raise_exception=True)
```

## 10. Swagger / OpenAPI (drf-spectacular)

Dristi uses `drf-spectacular` for OpenAPI generation.

Baseline configuration:

- Add `"drf_spectacular"` to `INSTALLED_APPS`.
- Set `REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"`.
- Add routes in `apps.api.urls`:
  - `path("schema/", SpectacularAPIView.as_view(), name="api-schema")`
  - `path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs")`

For custom endpoints/actions, prefer explicit schema annotations (for example with `@extend_schema`) so docs stay accurate.

Note: `SpectacularAPIView` may return vendor OpenAPI media types by default; use `?format=json` when JSON output is required in tests/tooling.

### Example: ApiVersionChangeLog (read-only)

Implemented example using the DRF-native base classes:

- Viewset: `src/apps/core/views.py`
- Serializer: `src/apps/core/serializers.py`
- Router registration: `src/apps/api/urls.py`

Endpoints:

- `GET /api/v1/api-version-changelogs/` (list)
- `GET /api/v1/api-version-changelogs/{id}/` (retrieve)

Swagger metadata is declared via `@extend_schema_view` on the viewset.

## 11. Pagination

Default DRF pagination config:

- `DEFAULT_PAGINATION_CLASS`: `rest_framework.pagination.PageNumberPagination`
- `PAGE_SIZE`: `20`

List endpoints built with DRF viewsets inherit these defaults automatically.

## 12. Background Jobs (Dramatiq)

When endpoints need asynchronous work:

- Define actors in `src/apps/<app>/tasks.py` using `@dramatiq.actor`.
- Enqueue from views/services with `.send(...)`.
- Keep actors idempotent and transactional where possible.
- Track delivery/state in persistent models when operational visibility is required (see `apps.messaging`).

## 13. Testing APIs

Use `rest_framework.test.APITestCase` and named URL reversing:

- `reverse("<route-name>")` or router names (for example `"user-list"`)
- Assert status code + response payload shape
- Add auth/non-auth coverage for protected endpoints

Examples live in `src/apps/api/tests.py`.

## 14. Implementation Checklist for New Endpoints

1. Add/modify model(s) in `src/apps/<app>/models.py` (inherit `BaseModel` unless justified otherwise).
2. Add serializer(s) in `src/apps/<app>/serializers.py` with explicit fields.
3. Add view/viewset logic in `src/apps/<app>/views.py`.
4. Register routes in `src/apps/<app>/urls.py`.
5. Include app URLs from `src/config/urls.py` if needed.
6. Add tests under `src/apps/<app>/tests/`.
7. Run checks:

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

## 15. Related Files

- `src/apps/core/models.py` — shared base models
- `src/apps/api/viewsets/base.py` — reusable DRF-native viewset base classes
- `src/apps/api/renderers.py` — global JSON response metadata renderer
- `src/apps/api/meta.py` — standard `meta` payload helper
- `src/apps/core/views.py` — `ApiVersionChangeLogViewSet` example using base classes
- `src/apps/core/serializers.py` — serializer example for model-backed read APIs
- `src/apps/api/views.py` — reference API patterns
- `src/apps/api/serializers.py` — reference serializer pattern
- `src/apps/api/urls.py` — routing + versioned endpoints
- `src/config/urls.py` — project URL mounting
- `src/config/settings/base.py` — DRF, auth, and global API + schema settings
- `src/apps/messaging/` — real-world service/task async workflow patterns
