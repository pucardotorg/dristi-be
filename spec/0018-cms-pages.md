# SS18 — CMS Simple Pages

## Status

Proposed

Revision 2 adds multi-language support (sections 2.1, 2.4–2.5, 5–9, 11–12).
Revision 3 moves the `Language` model, its API, error codes and language
resolution from `apps.cms` to `apps.core`, so other apps can localise content
without depending on cms.
Revision 4 adds `Language.supports`: the set of capabilities (UI, translation,
OCR, …) each language has.

## Context

Dristi needs a lightweight CMS capability for static/read-mostly pages (for example: About, FAQ, Help, Privacy Policy) that can be managed in admin and served via read APIs.

This spec introduces a dedicated `cms` app with a `Page` domain model and read-only APIs to list pages and fetch a page by slug, while conforming to the repository API conventions (`spec/0000-api-coding-spec.md`).

Dristi serves litigants and advocates who do not all read English. CMS content
(terms, privacy, support, help) must therefore be publishable in several
languages, and clients must be able to discover which languages are offered and
request content in one of them.

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
- Support multiple content languages:
  - a `Language` model holding the set of supported languages, managed in admin,
  - per-language page content (`title`, `sub_title`, `main_image_url`, `content`),
  - per-language category names,
  - a fallback to the default language when a translation is missing.
- Expose read APIs:
  - list supported languages
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
- Translating API error messages or other non-CMS responses. Django's
  `LocaleMiddleware` is **not** enabled; language selection here applies only to
  CMS content.
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
├── errors.py
├── serializers.py
├── views.py
├── urls.py
├── migrations/
└── tests/
    └── test_pages_api.py
```

Register `apps.cms` in `INSTALLED_APPS` and mount routes under `/api/v1/`.

The `Language` model and its API live in `apps.core` (section 2.1), shared
with any app that needs localised content:

- `src/apps/core/models.py` — `Language`
- `src/apps/core/admin.py` — `LanguageAdmin`
- `src/apps/core/errors.py` — language error codes
- `src/apps/core/languages.py` — request language resolution (section 6.1)
- `src/apps/core/serializers.py` — `LanguageSerializer`
- `src/apps/core/views.py` — `LanguageViewSet`
- `src/apps/core/tests/test_languages.py`, `test_languages_api.py`,
  `test_language_resolution.py`

### 2. Data model

#### 2.1 `Language`

Supported languages are stored as rows, not an enum, so a new language can be
added (or temporarily withdrawn) from admin without a code change or deploy.
The set is small and read on every CMS request, so its table is
cachalot-cached (section 3).

Model: `apps.core.models.Language` (table `core_language`). Languages are
shared reference data, not CMS content: notifications, PDF templates or error
copy may need them later, so the model, its admin and its read API live in
`apps.core`. CMS is one consumer and imports it; nothing in `apps.core`
imports cms.

`Language` extends `apps.core.models.BaseModel` and
`apps.core.models.BaseActivatableModel` (spec 0006).

| Field | Type | Notes |
|---|---|---|
| `code` | `CharField(max_length=20, unique=True, db_index=True)` | BCP 47 tag, stored lowercase, e.g. `en`, `ml`, `hi`, `en-in`. Must match `^[a-z]{2,3}(-[a-z0-9]{2,8})*$` (validated with `fullmatch`). |
| `name` | `CharField(max_length=100)` | English name, e.g. `Malayalam`. |
| `native_name` | `CharField(max_length=100)` | Name in the language itself, e.g. `മലയാളം`. Shown in language pickers. |
| `is_default` | `BooleanField(default=False)` | The fallback language. Exactly one row is the default. |
| `sort_order` | `PositiveSmallIntegerField(default=0)` | Display order in the languages API. |
| `is_active` | `BooleanField(default=True)` | From `BaseActivatableModel`. Inactive languages are hidden from the API and cannot be requested. |
| `supports` | `JSONField(default=list)` | Array of `LanguageSupport` enum values naming the capabilities this language has (see below). Empty means content-only. |

`LanguageSupport` choices (`models.TextChoices` on `Language`, v1):

- `UI = "ui"` — the web/mobile UI is translated into this language.
- `TRANSLATION = "translation"` — content/document translation is available in this language.
- `OCR = "ocr"` — scanned-document OCR works for this language's script.

`supports` is stored as a `JSONField` list of enum strings (for example
`["ui", "ocr"]`), not a Postgres `ArrayField`: the test suite runs on SQLite
(`config.settings.test`) and `ArrayField` is Postgres-only, whereas a JSON
array behaves identically on both databases and filters with
`supports__contains=<value>`. The enum is deliberately a code-level
`TextChoices` (not rows): capabilities are features of the product, so adding
one is a code change anyway; languages remain admin-managed rows.

`supports` is capability metadata for clients and other features (a UI
switcher lists `ui` languages, an OCR pipeline checks `ocr`). It does **not**
gate CMS language resolution — that is driven by `is_active` (section 6.1);
admins keep the two consistent.

Model `Meta`:

- `ordering = ("sort_order", "code")`
- `UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="core_language_single_default")`
- `CheckConstraint(condition=Q(is_default=False) | Q(is_active=True), name="core_language_default_is_active")`

Validation and behaviour:

- `code` is lowercased in `clean()` and `save()` (as `Page.slug` is), so `en-IN` and `en-in` cannot coexist.
- `supports` must be a list of distinct valid `LanguageSupport` values;
  `clean()` rejects unknown values and non-list input, and normalises to enum
  order (deduped) on save, so `["ocr", "ui", "ui"]` is stored as
  `["ui", "ocr"]`.
- The default language cannot be deactivated or deleted; deleting it is blocked
  with `on_delete=PROTECT` from translations (section 2.4) and a model check.
- `Language.objects.get_default()` returns the default row; it is a
  configuration error (`ImproperlyConfigured`) if none exists.

`apps.cms.models.PageTranslation` and `PageCategoryTranslation` reference it
as `apps.core.models.Language`.

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
| `language` | `ForeignKey(Language, on_delete=PROTECT, related_name="page_translations")` | |
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
| `language` | `ForeignKey(Language, on_delete=PROTECT, related_name="category_translations")` | |
| `name` | `CharField(max_length=100)` | Localised category label. |

`UniqueConstraint(fields=["category", "language"], name="cms_category_translation_unique_language")`.

A missing category translation falls back to `PageCategory.name`, so no
default-language category translation row is required.

### 3. Cacheability

`Language`, `Page` and `PageCategory` (and their translations) are read-mostly and should be cachalot-cacheable.

Implementation scope for cacheability:

- Include app label `cms` in `CACHALOT_ONLY_CACHABLE_APPS` (already the case), which covers the page and translation tables.
- Add table `core_language` to `CACHALOT_ONLY_CACHABLE_TABLES` (the `core` app
  as a whole stays uncached, per the comment in `base.py`).
- Do **not** add manual per-view cache initially.
- Rely on cachalot automatic invalidation on writes.
- Because the response body depends on the requested language, page responses
  must send `Vary: Accept-Language` so HTTP caches and CDNs key on it
  (section 6.1). The `lang` query parameter is part of the URL and needs no
  `Vary` entry.

Test expectations:

- repeated language list, page list and retrieve-by-slug queries should hit cache,
- writes to `Language`, `Page`, `PageTranslation`, `PageCategoryTranslation` or page-category mapping should invalidate relevant querysets.

### 4. Admin

Register `Language` in `apps.core.admin`, and `Page` and `PageCategory` in
`apps.cms.admin`.

`LanguageAdmin`:

- list display: `code`, `name`, `native_name`, `supports`, `is_default`, `is_active`, `sort_order`
- list editable: `sort_order`, `is_active`
- list filter: `is_active`, and a `supports` filter (capability membership via `supports__contains`)
- search fields: `code`, `name`, `native_name`
- `supports` is edited with a `MultipleChoiceField` + `CheckboxSelectMultiple`
  in the admin form (choices from `LanguageSupport`), mapped to the JSON list
- read-only audit fields from `BaseModel`
- deactivating or un-defaulting the only default language is rejected with a form error

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

Base paths: `/api/v1/languages/` (core) and `/api/v1/cms/pages/` (cms).

| Method | Path | Purpose |
|---|---|---|
| GET | `/languages/` | List of active supported languages (unpaginated). |
| GET | `/cms/pages/` | Paginated list of pages, in the requested language. |
| GET | `/cms/pages/slug/{slug}/` | Retrieve a single page by unique slug, in the requested language. |

Notes:

- These endpoints are read-only in v1.
- The page-by-slug endpoint is required even if internal id-based retrieve exists elsewhere.
- Swagger tags follow the owning app per spec 0000 section 10.2: `Core` for the
  languages endpoint, `CMS` for the page endpoints.
- Both page endpoints accept language selection (section 6.1). The languages endpoint does not.

### 6. API behavior standards

Follow `0000-api-coding-spec.md`:

- Use DRF serializers with explicit fields (`no __all__`).
- Keep read endpoints thin (business logic in model/service if needed). Language
  resolution lives in `apps.core.languages`, not in the views.
- Response JSON must include top-level `meta` (already enforced by `MetaJSONRenderer`).
- List endpoint must use project pagination shape.
- Add drf-spectacular schema annotations/tags.

Authentication/permission decision:

- CMS simple pages and the language list are public content.
- Explicitly set `permission_classes = [AllowAny]` on these read endpoints to override project default authenticated permissions.

#### 6.1 Language selection

Every CMS content endpoint resolves one **requested language** per request,
from the first source that yields an active language:

1. `lang` query parameter, e.g. `?lang=ml`. Matched case-insensitively against
   active `Language.code`. If present but not an active language code, the
   request fails with `400` and `E10001` (`field: "lang"`). An explicit choice
   is never silently ignored.
2. `Accept-Language` request header. Parsed per RFC 9110 with quality values;
   for each tag in descending `q` order, try an exact match, then its primary
   subtag (`en-IN` → `en`). Unknown or malformed tags are skipped, never an
   error, because browsers send arbitrary values.
3. The default language.

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
differs from the requested language when a fallback happened (section 7.3).

The resolver is a single function used by all language-aware endpoints:

```python
# apps/core/languages.py
def resolve_request_language(request) -> Language: ...
```

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

#### 6.3 Languages list behavior

- Returns active languages only, ordered by `sort_order`, then `code`.
- Optional `?supports=<capability>` filter (validated with a DRF `ChoiceField`
  over `LanguageSupport` via a filter serializer, as in the organizations
  app): restricts the list to languages that declare that capability
  (`supports__contains`). An invalid value fails validation with `E00005`
  (`field: "supports"`); no new error code is needed.
- Unpaginated: the set is small and clients need all of it to build a picker.
  The action/view is listed in `unpaginated_actions` (or the view is a plain
  list view returning the whole set) so the schema documents
  `{"data": [...], "meta": ...}`.

### 7. Serializer contract

#### 7.1 `LanguageSerializer`

Fields:

- `code`
- `name`
- `native_name`
- `is_default`
- `supports`

Read-only. `id`, `sort_order` and `is_active` are not exposed: clients address
languages by `code`, receive them already ordered, and only see active ones.

#### 7.2 `PageCategorySerializer`

Fields:

- `id`
- `name` (localised, with fallback to `PageCategory.name`)
- `slug`

Read-only for API v1.

#### 7.3 `PageSerializer`

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

#### 8.1 List supported languages

`GET /api/v1/languages/`

```json
{
  "data": [
    {"code": "en", "name": "English", "native_name": "English", "is_default": true, "supports": ["ui", "translation", "ocr"]},
    {"code": "ml", "name": "Malayalam", "native_name": "മലയാളം", "is_default": false, "supports": ["ui", "translation"]},
    {"code": "hi", "name": "Hindi", "native_name": "हिन्दी", "is_default": false, "supports": ["translation"]}
  ],
  "meta": {
    "timestamp": "2026-10-13T12:30:00+05:30",
    "app_version": "<git-sha>",
    "spec_version": "1.0"
  }
}
```

#### 8.2 List pages

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

#### 8.3 Get page by slug

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

#### 8.4 Unsupported language

`GET /api/v1/cms/pages/slug/terms/?lang=xx` → `400`

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

Allocate domain `10` → `core` in `apps.api.errors.DOMAINS` and in the table in
spec 0000 section 9.2. Define codes in `src/apps/core/errors.py` (the language
codes are shared; cms defines no codes of its own for this feature):

| Code | Status | Default message | When |
|---|---|---|---|
| `E10001` | 400 | `Language is not supported.` | `lang` query parameter is not an active language code (`field: "lang"`). |

Unknown slugs keep returning the common `404` (`E00105`).

### 10. URL routing and wiring

- `path("api/v1/", include("apps.cms.urls"))` in `src/config/urls.py` is already present.
- In `src/apps/cms/urls.py`, register `cms/pages` (existing, unchanged).
- In `src/apps/api/urls.py`, register `languages` on the existing router
  (`apps.core.views.LanguageViewSet`, list only, `basename="language"`), next
  to `api-version-changelogs`. The languages endpoint is core-owned, so it
  does not live under the cms prefix.

### 11. Migrations and seed data

Revision 1 migrations (`0001_initial`, `0002_seed_default_pages`) are released
and must not be edited. Revision 2/3 adds:

1. `core/0007_language` — create `apps.core.models.Language` and its constraints.
2. `core/0008_seed_languages` (data migration, reversible) — seed the languages
   in section 11.1.
3. `cms/0003_page_translations` — create `PageTranslation` and
   `PageCategoryTranslation` (depends on `core/0007_language` for the FK).
4. `cms/0004_move_content_to_translations` (data migration, reversible):
   - for every existing `Page`, create an `en` `PageTranslation` copying
     `title`, `sub_title`, `main_image_url` and `content` (this also covers any
     pages created in admin since revision 1).
   - Reverse: copy `en` translations back onto `Page`.
5. `cms/0005_remove_page_translatable_fields` — drop `title`, `sub_title`,
   `main_image_url` and `content` from `Page` and change `Page.Meta.ordering`.

#### 11.1 Seed languages

| `code` | `name` | `native_name` | `is_default` | `sort_order` | `is_active` | `supports` |
|---|---|---|---|---|---|---|
| `en` | English | English | yes | 0 | yes | `["ui", "translation", "ocr"]` |
| `ml` | Malayalam | മലയാളം | no | 10 | yes | `["ui", "translation"]` |
| `hi` | Hindi | हिन्दी | no | 20 | yes | `["translation"]` |

Seeding uses `update_or_create(code=...)` so it is idempotent.

#### 11.2 Seed categories (revision 1, unchanged)

Create these `PageCategory` rows:

1. `Help` (`slug=help`)
2. `Main` (`slug=main`)
3. `FAQ` (`slug=faq`)

No category translations are seeded; non-English requests fall back to these names.

#### 11.3 Seed pages (revision 1, content moved to `en` translations)

Create these `Page` rows and map all of them to category `Main`:

1. `slug=terms`, `title=Terms of Use`
2. `slug=privacy`, `title=Privacy`
3. `slug=support`, `title=Support`

For each page:

- `content_type = markdown`
- `content` should be dummy markdown content (non-empty placeholder text)
- `sub_title` and `main_image_url` may be left blank in seed data
- after migration `0004`, this content lives in the page's `en` translation; no `ml`/`hi` page translations are seeded

### 12. Tests

Add API and model tests covering at least:

1. slug validator accepts `about-us`, `page1`, rejects `about_us`, `about us`, `about@us`.
2. unique slug constraint enforced.
3. list endpoint returns paginated response with `meta`.
4. slug endpoint returns 200 for existing slug, 404 for unknown slug.
5. schema contains the `CMS` tag and `/api/v1/cms/pages/` endpoints, the `Core`
   tag and `/api/v1/languages/` endpoint, and the `lang` parameter on both page
   endpoints.
6. cachalot behavior for language/page reads + invalidation on writes (including translation writes).
7. seeded languages, categories and pages are present; pages are related to `Main` and have an `en` translation.

Language support:

8. `Language`: code validator accepts `en`, `ml`, `en-in`, rejects `EN_IN`, `e`, `en-`, `en\n`; code is lowercased on save; only one default allowed; default cannot be inactive.
9. `GET /api/v1/languages/` is public, unpaginated (`data` + `meta`), returns only active languages in `sort_order`, and exposes exactly `code`, `name`, `native_name`, `is_default`, `supports`.
9a. `supports` accepts only known `LanguageSupport` values, rejects duplicates
   and non-list input, and is normalised to enum order on save.
9b. `?supports=ui` returns only languages declaring `ui`; `?supports=bogus`
   returns `400` with code `E00005` and field `supports`.
10. Resolution order: `lang` beats `Accept-Language`; `Accept-Language` beats the default; `q` values are honoured; `en-IN` matches `en`; unknown or malformed `Accept-Language` falls back to the default without error.
11. `?lang=xx` and `?lang=<inactive code>` return `400` with code `E10001` and field `lang` on both page endpoints.
12. Fallback: a page without a translation in the requested language is served in the default language with `language` set accordingly; category names fall back to `PageCategory.name`.
13. A page without a default-language translation is absent from the list and 404 on the slug endpoint.
14. `available_languages` lists only active languages that have a translation.
15. Page responses carry `Content-Language` and `Vary: Accept-Language`.
16. List ordering follows the served (localised) title; query count is constant in page size.
17. Requests without any language selection return the same content as revision 1 (backward compatibility).
18. Migration `0004` moves existing page content into `en` translations and reverses cleanly.

## Affected files

- `src/config/settings/base.py` (add `core_language` to `CACHALOT_ONLY_CACHABLE_TABLES`)
- `src/apps/api/urls.py` (register the `languages` route)
- `src/apps/api/errors.py` (allocate domain `10` → `core`)
- `spec/0000-api-coding-spec.md` (domain table, section 9.2)
- `src/apps/core/models.py` (`Language`)
- `src/apps/core/admin.py` (`LanguageAdmin`)
- `src/apps/core/errors.py`
- `src/apps/core/languages.py`
- `src/apps/core/serializers.py` (`LanguageSerializer`)
- `src/apps/core/views.py` (`LanguageViewSet`)
- `src/apps/core/migrations/0007_language.py`
- `src/apps/core/migrations/0008_seed_languages.py`
- `src/apps/core/tests/test_languages.py`
- `src/apps/core/tests/test_languages_api.py`
- `src/apps/core/tests/test_language_resolution.py`
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

## Open questions

- Should category be represented as a dedicated model (`PageCategory`) only, or also support free-text tags later?
- Should we add publish state/scheduling (`is_published`, `published_at`) in v1, or keep all pages visible?
- Should CMS resolution prefer languages with `translation` in `supports` over
  merely `is_active` ones? For now `supports` is informational only.
- Should the list endpoint offer a strict mode (for example `?fallback=false`)
  that returns only pages translated into the requested language?
- Should `hi` be active from day one, or seeded inactive until content is translated?

## Related specs

- `0000-api-coding-spec.md` — API conventions, response metadata, error codes, schema, testing.
- `0002-audit-fields-base-model.md` — base audited model behavior.
- `0006-active-flag-model.md` — `is_active` mixin used by `Language`.
- `0012-redis-caching.md` — cachalot-based cache strategy.
