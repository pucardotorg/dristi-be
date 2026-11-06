# SS18 — CMS Simple Pages

## Status

Proposed

Revision 2 adds multi-language support.
Revision 5 extracts the shared language model, languages API, resolver and
language error codes into `0030-core-language-support.md`. This spec keeps
only CMS-owned behavior and depends on 0030.

## Context

Dristi needs a lightweight CMS capability for static/read-mostly pages (for example: About, FAQ, Help, Privacy Policy) that can be managed in admin and served via read APIs.

This spec introduces a dedicated `cms` app with a `Page` domain model and read-only APIs to list pages and fetch a page by slug, while conforming to the repository API conventions (`spec/0000-api-coding-spec.md`).

Dristi serves litigants and advocates who do not all read English. CMS content
(terms, privacy, support, help) must therefore be publishable in several
languages, and clients must be able to request content in one of them. The
shared language registry and resolver come from spec 0030.

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
- Support multiple content languages (using `apps.core.models.Language`, spec 0030):
  - per-language page content (`title`, `sub_title`, `main_image_url`, `content`),
  - per-language category names,
  - a fallback to the default language when a translation is missing.
- Expose read APIs:
  - list pages
  - get page by slug
- Every CMS content API accepts a language selection and reports the language served.
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
- Machine translation or translation workflow (review/approval of translations).
- The language registry, languages list API and language resolution rules —
  owned by spec 0030.
- Right-to-left layout hints (none of the initial languages need them).

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
    ├── test_pages_api.py
    ├── test_models.py
    └── test_caching.py
```

Register `apps.cms` in `INSTALLED_APPS` and mount routes under `/api/v1/`.

The `Language` model, its admin/API, `resolve_request_language` and the
language error codes live in `apps.core` (spec 0030). CMS imports them;
nothing in `apps.core` imports cms.

### 2. Data model

#### 2.1 `Language` (spec 0030)

Languages are `apps.core.models.Language` rows (spec 0030), not a cms-owned
model. `PageTranslation` and `PageCategoryTranslation` below reference it with
`on_delete=PROTECT`, which also prevents deleting a language that still has
content.

#### 2.2 `PageCategory`

A minimal category model is required because `Page.category` is many-to-many.

Model: `apps.cms.models.PageCategory`

| Field | Type | Notes |
|---|---|---|
| `name` | `CharField(max_length=100, unique=True)` | Display/category label in the default language. Also the fallback when a translation is missing. |
| `slug` | `SlugField(max_length=120, unique=True)` | Optional API/admin friendly stable identifier. Uses Django slug format (lowercase recommended). Language-independent. |

`PageCategory` also extends `BaseModel`.

#### 2.3 `Page`

Model: `apps.cms.models.Page`

`Page` extends `apps.core.models.BaseModel`. After revision 2, `Page` holds only
the language-independent attributes. Translatable content moves to
`PageTranslation` (section 2.4).

| Field | Type | Notes |
|---|---|---|
| `slug` | `CharField(max_length=150, unique=True, db_index=True)` | Must match `^[A-Za-z0-9-]+$` (alphanumeric + `-` only). Stored lowercase. **Shared by all languages**: `terms` identifies the Terms page in every language. |
| `content_type` | `CharField(max_length=30, choices=ContentType.choices, default=markdown)` | Enum with one value for now: `markdown`. Applies to all translations. |
| `categories` | `ManyToManyField(PageCategory, related_name="pages", blank=True)` | Page-category relation. Shared by all languages. |

`ContentType` choices (v1):

- `MARKDOWN = "markdown"`

Model `Meta` recommendations:

- `ordering = ("slug",)` (title is now per-language; API ordering is in section 6.2)
- `verbose_name = "Page"`
- `verbose_name_plural = "Pages"`

Validation:

- Reject slugs that include `_`, spaces, or other special characters.
- Slug uniqueness must be enforced at DB + model validation level.
- `content_type` must be one of supported enum values.
- A page must have a translation in the default language (enforced in admin,
  see section 4; pages without one are excluded from the API).

#### 2.4 `PageTranslation`

Model: `apps.cms.models.PageTranslation`, extends `BaseModel`.

| Field | Type | Notes |
|---|---|---|
| `page` | `ForeignKey(Page, on_delete=CASCADE, related_name="translations")` | |
| `language` | `ForeignKey(apps.core.models.Language, on_delete=PROTECT, related_name="page_translations")` | |
| `title` | `CharField(max_length=255)` | Required. |
| `sub_title` | `CharField(max_length=255, blank=True)` | Optional. |
| `main_image_url` | `URLField(max_length=500, blank=True)` | Per language, because banner images often contain text. |
| `content` | `TextField()` | Raw markdown/text payload in this language. |

Model `Meta`:

- `UniqueConstraint(fields=["page", "language"], name="cms_page_translation_unique_language")`
- `ordering = ("page", "language__sort_order")`

#### 2.5 `PageCategoryTranslation`

Model: `apps.cms.models.PageCategoryTranslation`, extends `BaseModel`.

| Field | Type | Notes |
|---|---|---|
| `category` | `ForeignKey(PageCategory, on_delete=CASCADE, related_name="translations")` | |
| `language` | `ForeignKey(apps.core.models.Language, on_delete=PROTECT, related_name="category_translations")` | |
| `name` | `CharField(max_length=100)` | Localised category label. |

`UniqueConstraint(fields=["category", "language"], name="cms_category_translation_unique_language")`.

A missing category translation falls back to `PageCategory.name`, so no
default-language category translation row is required.

### 3. Cacheability

`Page` and `PageCategory` (and their translations) are read-mostly and should be cachalot-cacheable.

Implementation scope for cacheability:

- Include app label `cms` in `CACHALOT_ONLY_CACHABLE_APPS` (already the case), which covers the page and translation tables.
- `core_language` caching is owned by spec 0030.
- Do **not** add manual per-view cache initially.
- Rely on cachalot automatic invalidation on writes.
- Because the response body depends on the requested language, page responses
  must send `Vary: Accept-Language` so HTTP caches and CDNs key on it
  (section 6.1). The `lang` query parameter is part of the URL and needs no
  `Vary` entry.

Test expectations:

- repeated page list and retrieve-by-slug queries should hit cache,
- writes to `Page`, `PageTranslation`, `PageCategoryTranslation` or page-category mapping should invalidate relevant querysets.

### 4. Admin

Register `Page` and `PageCategory` in `apps.cms.admin` (`LanguageAdmin` lives
in `apps.core.admin`, spec 0030).

`PageAdmin`:

- list display: `slug`, default-language title, `content_type`, translated languages (comma-separated codes), `created_at`, `updated_at`
- search fields: `slug`, `translations__title`, `translations__sub_title`
- list filter: `content_type`, `categories`, `translations__language`
- `filter_horizontal` (or autocomplete) for categories
- `PageTranslationInline` (stacked) for per-language content; the formset
  requires a translation in the default language and rejects duplicate languages
- read-only audit fields from `BaseModel`

`PageCategoryAdmin`:

- list display: `name`, `slug`, `created_at`, `updated_at`
- search fields: `name`, `slug`, `translations__name`
- `PageCategoryTranslationInline` (tabular)

### 5. API surface (read-only)

Base path: `/api/v1/cms/pages/`

| Method | Path | Purpose |
|---|---|---|
| GET | `/cms/pages/` | Paginated list of pages, in the requested language. |
| GET | `/cms/pages/slug/{slug}/` | Retrieve a single page by unique slug, in the requested language. |

The languages list (`GET /api/v1/languages/`) is a core endpoint, spec 0030.

Notes:

- These endpoints are read-only in v1.
- The page-by-slug endpoint is required even if internal id-based retrieve exists elsewhere.
- Swagger tag: `CMS` (inferred from the owning app per spec 0000 section 10.2).
- Both page endpoints accept language selection (section 6.1).

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

#### 6.1 Language selection and fallback

Both page endpoints resolve the requested language with
`apps.core.languages.resolve_request_language` (spec 0030 section 5): `lang`
query parameter, then `Accept-Language` header, then the default language. An
unknown or inactive `lang` value fails with `400` / `E10001`
(`field: "lang"`).

Content is then served per object, with fallback:

- For each page, the translation in the requested language is used; if it does
  not exist, the default-language translation is used.
- For each category, the translation in the requested language is used; if it
  does not exist, `PageCategory.name` is used.
- A page with no default-language translation is excluded from both page
  endpoints (the slug endpoint returns `404`).

Response headers on page endpoints:

- `Content-Language: <requested language code>`
- `Vary: Accept-Language`

Each page in the body carries the `language` it was actually served in, which
differs from the requested language when a fallback happened (section 7.2).

The `lang` parameter is declared once in OpenAPI
(`OpenApiParameter("lang", str, OpenApiParameter.QUERY, ...)`) on both page
endpoints, with the `E10001` example attached via `error_responses(...)`.

#### 6.2 Page list behavior

- Returns every page that has a default-language translation, each rendered in
  the requested language with fallback (section 6.1).
- Ordered by the served title, then slug. Implemented with an annotated
  `Coalesce` over the requested-language and default-language titles, so
  ordering and pagination happen in the database.
- Querysets prefetch translations limited to the requested and default
  languages (`Prefetch("translations", queryset=...filter(language__in=[requested, default]))`),
  and the same for category translations, so the number of queries is constant
  regardless of page size.

### 7. Serializer contract

#### 7.1 `PageCategorySerializer`

Fields:

- `id`
- `name` (localised, with fallback to `PageCategory.name`)
- `slug`

Read-only for API v1.

#### 7.2 `PageSerializer`

Fields:

- `id`
- `slug`
- `language` (code of the translation actually served)
- `available_languages` (codes of active languages this page has a translation in, in `sort_order`)
- `title`
- `sub_title`
- `main_image_url`
- `content_type`
- `content`
- `categories` (nested category serializer, localised)
- `created_at`
- `updated_at`

All read-only for v1. The requested and default languages are passed in the
serializer context by the view; the serializer never re-resolves the language.

`title`, `sub_title`, `main_image_url` and `content` keep their revision-1
names and positions, so existing clients that ignore the new keys keep working
and receive default-language (English) content when they send no language.

`updated_at` is the later of the page's and the served translation's
`updated_at`, so clients see a change when only a translation was edited.

### 8. API examples

#### 8.1 List pages

`GET /api/v1/cms/pages/?lang=ml`

Response headers include `Content-Language: ml` and `Vary: Accept-Language`.

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": "6a9e3f43-3a44-4f75-9c86-6e872f0dd3ef",
      "slug": "terms",
      "language": "ml",
      "available_languages": ["en", "ml"],
      "title": "ഉപയോഗ നിബന്ധനകൾ",
      "sub_title": "",
      "main_image_url": "",
      "content_type": "markdown",
      "content": "# ഉപയോഗ നിബന്ധനകൾ\n...",
      "categories": [
        {"id": "43c7...", "name": "പ്രധാനം", "slug": "main"}
      ],
      "created_at": "2026-10-13T07:00:00Z",
      "updated_at": "2026-10-14T09:15:00Z"
    },
    {
      "id": "0b1d...",
      "slug": "privacy",
      "language": "en",
      "available_languages": ["en"],
      "title": "Privacy",
      "sub_title": "",
      "main_image_url": "",
      "content_type": "markdown",
      "content": "# Privacy\n\nDummy markdown content.",
      "categories": [
        {"id": "43c7...", "name": "പ്രധാനം", "slug": "main"}
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

The `privacy` page has no Malayalam translation, so it is served in English
(`"language": "en"`), while its category name is still localised.

#### 8.2 Get page by slug

`GET /api/v1/cms/pages/slug/terms/` with `Accept-Language: ml-IN, en;q=0.8`

```json
{
  "id": "6a9e3f43-3a44-4f75-9c86-6e872f0dd3ef",
  "slug": "terms",
  "language": "ml",
  "available_languages": ["en", "ml"],
  "title": "ഉപയോഗ നിബന്ധനകൾ",
  "sub_title": "",
  "main_image_url": "",
  "content_type": "markdown",
  "content": "# ഉപയോഗ നിബന്ധനകൾ\n...",
  "categories": [
    {"id": "43c7...", "name": "പ്രധാനം", "slug": "main"}
  ],
  "created_at": "2026-10-13T07:00:00Z",
  "updated_at": "2026-10-14T09:15:00Z",
  "meta": {
    "timestamp": "2026-10-13T12:30:00+05:30",
    "app_version": "<git-sha>",
    "spec_version": "1.0"
  }
}
```

#### 8.3 Unsupported language

`GET /api/v1/cms/pages/slug/terms/?lang=xx` → `400` (`E10001` is defined in
spec 0030 section 8)

```json
{
  "errors": [
    {"code": "E10001", "message": "Language \"xx\" is not supported.", "field": "lang"}
  ],
  "meta": {
    "timestamp": "2026-10-13T12:30:00+05:30",
    "app_version": "<git-sha>",
    "spec_version": "1.0"
  }
}
```

### 9. Error codes

CMS defines no codes of its own for this feature. The unsupported-language
error `E10001` belongs to the `core` domain (spec 0030 section 8).

Unknown slugs keep returning the common `404` (`E00105`).

### 10. URL routing and wiring

- `path("api/v1/", include("apps.cms.urls"))` in `src/config/urls.py` is already present.
- In `src/apps/cms/urls.py`, register `cms/pages` (existing, unchanged).
- The `languages` route is registered by spec 0030 in `src/apps/api/urls.py`.

### 11. Migrations and seed data

Revision 1 migrations (`0001_initial`, `0002_seed_default_pages`) are released
and must not be edited. Revision 2 adds (the `core/0007_language` and
`core/0008_seed_languages` migrations are owned by spec 0030):

1. `cms/0003_page_translations` — create `PageTranslation` and
   `PageCategoryTranslation` (depends on `core/0007_language` for the FK).
2. `cms/0004_move_content_to_translations` (data migration, reversible):
   - for every existing `Page`, create an `en` `PageTranslation` copying
     `title`, `sub_title`, `main_image_url` and `content` (this also covers any
     pages created in admin since revision 1).
   - Reverse: copy `en` translations back onto `Page`.
3. `cms/0005_remove_page_translatable_fields` — drop `title`, `sub_title`,
   `main_image_url` and `content` from `Page` and change `Page.Meta.ordering`.

#### 11.1 Seed categories (revision 1, unchanged)

Create these `PageCategory` rows:

1. `Help` (`slug=help`)
2. `Main` (`slug=main`)
3. `FAQ` (`slug=faq`)

No category translations are seeded; non-English requests fall back to these names.

#### 11.2 Seed pages (revision 1, content moved to `en` translations)

Create these `Page` rows and map all of them to category `Main`:

1. `slug=terms`, `title=Terms of Use`
2. `slug=privacy`, `title=Privacy`
3. `slug=support`, `title=Support`

For each page:

- `content_type = markdown`
- `content` should be dummy markdown content (non-empty placeholder text)
- `sub_title` and `main_image_url` may be left blank in seed data
- after migration `0004`, this content lives in the page's `en` translation; no
  `ml`/`hi` page translations are seeded (the languages themselves are seeded
  by spec 0030)

### 12. Tests

Add API and model tests covering at least (language model, languages API,
resolver and seed tests live in `apps.core`, spec 0030 section 11):

1. slug validator accepts `about-us`, `page1`, rejects `about_us`, `about us`, `about@us`.
2. unique slug constraint enforced.
3. list endpoint returns paginated response with `meta`.
4. slug endpoint returns 200 for existing slug, 404 for unknown slug.
5. schema contains the `CMS` tag and `/api/v1/cms/pages/` endpoints, and the
   `lang` parameter on both page endpoints.
6. cachalot behavior for page reads + invalidation on writes (including translation writes).
7. seeded categories and pages are present; pages are related to `Main` and have an `en` translation.

Language support:

8. `?lang=xx` and `?lang=<inactive code>` return `400` with code `E10001` and field `lang` on both page endpoints.
9. `Accept-Language` selects the language when no `lang` parameter is given; `lang` wins over the header.
10. Fallback: a page without a translation in the requested language is served in the default language with `language` set accordingly; category names fall back to `PageCategory.name`.
11. A page without a default-language translation is absent from the list and 404 on the slug endpoint.
12. `available_languages` lists only active languages that have a translation.
13. Page responses carry `Content-Language` and `Vary: Accept-Language`.
14. List ordering follows the served (localised) title; query count is constant in page size.
15. Requests without any language selection return the same content as revision 1 (backward compatibility).
16. Migration `0004` moves existing page content into `en` translations and reverses cleanly.

## Affected files

- `src/config/urls.py` (already wired)
- `src/apps/cms/models.py`
- `src/apps/cms/admin.py`
- `src/apps/cms/serializers.py`
- `src/apps/cms/views.py`
- `src/apps/cms/urls.py`
- `src/apps/cms/migrations/0003_page_translations.py`
- `src/apps/cms/migrations/0004_move_content_to_translations.py`
- `src/apps/cms/migrations/0005_remove_page_translatable_fields.py`
- `src/apps/cms/tests/test_pages_api.py`
- `src/apps/cms/tests/test_models.py`
- `src/apps/cms/tests/test_caching.py`

Core-owned files (`Language`, its admin/API, resolver, error codes, seed
migrations, `core_language` cache entry) are listed in spec 0030.

## Open questions

- Should category be represented as a dedicated model (`PageCategory`) only, or also support free-text tags later?
- Should we add publish state/scheduling (`is_published`, `published_at`) in v1, or keep all pages visible?
- Should the list endpoint offer a strict mode (for example `?fallback=false`)
  that returns only pages translated into the requested language?

## Related specs

- `0000-api-coding-spec.md` — API conventions, response metadata, schema, testing.
- `0002-audit-fields-base-model.md` — base audited model behavior.
- `0012-redis-caching.md` — cachalot-based cache strategy.
- `0030-core-language-support.md` — language registry, capabilities, languages API, resolver, language error codes.
