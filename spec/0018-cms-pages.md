# SS18 — CMS Simple Pages

## Status

Proposed

## Context

Dristi needs a lightweight CMS capability for static/read-mostly pages (for example: About, FAQ, Help, Privacy Policy) that can be managed in admin and served via read APIs.

This spec introduces a dedicated `cms` app with a `Page` domain model and read-only APIs to list pages and fetch a page by slug, while conforming to the repository API conventions (`spec/0000-api-coding-spec.md`).

## Goals

- Add a separate Django app: `apps.cms`.
- Introduce a cacheable `Page` model that extends `BaseModel`.
- Support page fields:
  - `slug` (unique; alphanumeric + hyphen `-` only)
  - `title`
  - `sub_title`
  - `main_image_url`
  - `content_type` (currently only `markdown`)
  - `content` (text)
  - `category` (many-to-many)
- Expose read APIs:
  - list pages
  - get page by slug
- Follow existing API standards:
  - DRF serializers
  - DRF view/viewset patterns
  - OpenAPI tags via drf-spectacular
  - response `meta` envelope
  - pagination on list endpoints

## Non-goals

- Rich-text editors, media upload workflows, or markdown rendering.
- Page revision/version history beyond existing audit timestamps in `BaseModel`.
- Public write APIs for CMS content.
- SEO sitemap generation.

## Proposed changes

### 1. App layout

Create a dedicated Django app:

```text
src/apps/cms/
├── __init__.py
├── apps.py
├── models.py
├── admin.py
├── serializers.py
├── views.py
├── urls.py
├── migrations/
└── tests/
    └── test_pages_api.py
```

Register `apps.cms` in `INSTALLED_APPS` and mount routes under `/api/v1/`.

### 2. Data model

#### 2.1 `PageCategory`

A minimal category model is required because `Page.category` is many-to-many.

Model: `apps.cms.models.PageCategory`

| Field | Type | Notes |
|---|---|---|
| `name` | `CharField(max_length=100, unique=True)` | Display/category label. |
| `slug` | `SlugField(max_length=120, unique=True)` | Optional API/admin friendly stable identifier. Uses Django slug format (lowercase recommended). |

`PageCategory` also extends `BaseModel`.

#### 2.2 `Page`

Model: `apps.cms.models.Page`

`Page` extends `apps.core.models.BaseModel`.

| Field | Type | Notes |
|---|---|---|
| `slug` | `CharField(max_length=150, unique=True, db_index=True)` | Must match `^[A-Za-z0-9-]+$` (alphanumeric + `-` only). |
| `title` | `CharField(max_length=255)` | Required page title. |
| `sub_title` | `CharField(max_length=255, blank=True)` | Optional subtitle. |
| `main_image_url` | `URLField(max_length=500, blank=True)` | Optional absolute URL. |
| `content_type` | `CharField(max_length=30, choices=ContentType.choices, default=markdown)` | Enum with one value for now: `markdown`. |
| `content` | `TextField()` | Raw markdown/text payload. |
| `categories` | `ManyToManyField(PageCategory, related_name="pages", blank=True)` | Page-category relation. |

`ContentType` choices (v1):

- `MARKDOWN = "markdown"`

Model `Meta` recommendations:

- `ordering = ("title", "slug")`
- `verbose_name = "Page"`
- `verbose_name_plural = "Pages"`

Validation:

- Reject slugs that include `_`, spaces, or other special characters.
- Slug uniqueness must be enforced at DB + model validation level.
- `content_type` must be one of supported enum values.

### 3. Cacheability

`Page` is read-mostly and should be cachalot-cacheable.

Implementation scope for cacheability:

- Include app label `cms` in `CACHALOT_ONLY_CACHABLE_APPS` (or include explicit page/category tables in `CACHALOT_ONLY_CACHABLE_TABLES`, consistent with the project’s selected strategy).
- Do **not** add manual per-view cache initially.
- Rely on cachalot automatic invalidation on writes.

Test expectations:

- repeated page list/retrieve-by-slug queries should hit cache,
- writes to `Page` or page-category mapping should invalidate relevant querysets.

### 4. Admin

Register both models in `apps.cms.admin`.

`PageAdmin`:

- list display: `slug`, `title`, `content_type`, `created_at`, `updated_at`
- search fields: `slug`, `title`, `sub_title`
- list filter: `content_type`, `categories`
- `filter_horizontal` (or autocomplete) for categories
- read-only audit fields from `BaseModel`

`PageCategoryAdmin`:

- list display: `name`, `slug`, `created_at`, `updated_at`
- search fields: `name`, `slug`

### 5. API surface (read-only)

Base path: `/api/v1/cms/pages/`

| Method | Path | Purpose |
|---|---|---|
| GET | `/cms/pages/` | Paginated list of pages. |
| GET | `/cms/pages/slug/{slug}/` | Retrieve a single page by unique slug. |

Notes:

- These endpoints are read-only in v1.
- The page-by-slug endpoint is required even if internal id-based retrieve exists elsewhere.
- Swagger tags: `CMS`.

### 6. API behavior standards

Follow `0000-api-coding-spec.md`:

- Use DRF serializers with explicit fields (`no __all__`).
- Keep read endpoints thin (business logic in model/service if needed).
- Response JSON must include top-level `meta` (already enforced by `MetaJSONRenderer`).
- List endpoint must use project pagination shape.
- Add drf-spectacular schema annotations/tags.

Authentication/permission decision:

- CMS simple pages are public content.
- Explicitly set `permission_classes = [AllowAny]` on these read endpoints to override project default authenticated permissions.

### 7. Serializer contract

#### 7.1 `PageCategorySerializer`

Fields:

- `id`
- `name`
- `slug`

Read-only for API v1.

#### 7.2 `PageSerializer`

Fields:

- `id`
- `slug`
- `title`
- `sub_title`
- `main_image_url`
- `content_type`
- `content`
- `categories` (nested category serializer)
- `created_at`
- `updated_at`

All read-only for v1.

### 8. API examples

#### 8.1 List pages

`GET /api/v1/cms/pages/`

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "6a9e3f43-3a44-4f75-9c86-6e872f0dd3ef",
      "slug": "terms",
      "title": "Terms of Use",
      "sub_title": "",
      "main_image_url": "",
      "content_type": "markdown",
      "content": "# Terms of Use\nDummy markdown content.",
      "categories": [
        {"id": "43c7...", "name": "Main", "slug": "main"}
      ],
      "created_at": "2026-10-13T07:00:00Z",
      "updated_at": "2026-10-13T07:00:00Z"
    }
  ],
  "meta": {
    "timestamp": "2026-10-13T12:30:00+05:30",
    "app_version": "<git-sha>",
    "spec_version": "1.0"
  }
}
```

#### 8.2 Get page by slug

`GET /api/v1/cms/pages/slug/terms/`

```json
{
  "id": "6a9e3f43-3a44-4f75-9c86-6e872f0dd3ef",
  "slug": "terms",
  "title": "Terms of Use",
  "sub_title": "",
  "main_image_url": "",
  "content_type": "markdown",
  "content": "# Terms of Use\nDummy markdown content.",
  "categories": [
    {"id": "43c7...", "name": "Main", "slug": "main"}
  ],
  "created_at": "2026-10-13T07:00:00Z",
  "updated_at": "2026-10-13T07:00:00Z",
  "meta": {
    "timestamp": "2026-10-13T12:30:00+05:30",
    "app_version": "<git-sha>",
    "spec_version": "1.0"
  }
}
```

### 9. URL routing and wiring

- Add `path("api/v1/", include("apps.cms.urls"))` in `src/config/urls.py`.
- Add router registration so routes are exposed as `/cms/pages/...` in `src/apps/cms/urls.py`.
- Add `apps.cms` to `INSTALLED_APPS`.

### 10. Seed data (categories + initial pages)

Add a data migration to seed default categories and initial pages.

#### 10.1 Seed categories

Create these `PageCategory` rows:

1. `Help` (`slug=help`)
2. `Main` (`slug=main`)
3. `FAQ` (`slug=faq`)

#### 10.2 Seed pages

Create these `Page` rows and map all of them to category `Main`:

1. `slug=terms`, `title=Terms of Use`
2. `slug=privacy`, `title=Privacy`
3. `slug=support`, `title=Support`

For each page:

- `content_type = markdown`
- `content` should be dummy markdown content (non-empty placeholder text)
- `sub_title` and `main_image_url` may be left blank in seed data

### 11. Tests

Add API and model tests covering at least:

1. slug validator accepts `about-us`, `page1`, rejects `about_us`, `about us`, `about@us`.
2. unique slug constraint enforced.
3. list endpoint returns paginated response with `meta`.
4. slug endpoint returns 200 for existing slug, 404 for unknown slug.
5. schema contains `CMS` tag and `/api/v1/cms/pages/` endpoints.
6. cachalot behavior for page reads + invalidation on writes.
7. seeded categories and pages are present and correctly related to `Main`.

## Affected files

- `src/config/settings/base.py` (cache allow-list and app registration)
- `src/config/urls.py`
- `src/apps/cms/__init__.py`
- `src/apps/cms/apps.py`
- `src/apps/cms/models.py`
- `src/apps/cms/admin.py`
- `src/apps/cms/serializers.py`
- `src/apps/cms/views.py`
- `src/apps/cms/urls.py`
- `src/apps/cms/migrations/<seed_default_categories_and_pages>.py`
- `src/apps/cms/tests/test_pages_api.py`
- `src/apps/cms/tests/test_models.py`

## Open questions

- Should category be represented as a dedicated model (`PageCategory`) only, or also support free-text tags later?
- Should we add publish state/scheduling (`is_published`, `published_at`) in v1, or keep all pages visible?

## Related specs

- `0000-api-coding-spec.md` — API conventions, response metadata, schema, testing.
- `0002-audit-fields-base-model.md` — base audited model behavior.
- `0012-redis-caching.md` — cachalot-based cache strategy.
