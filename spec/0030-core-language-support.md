# SS30 — Core Language Support

## Status

Proposed

Extracted from `0018-cms-pages.md` (revisions 2–4), where multi-language
support originated. CMS remains the first consumer; this spec owns everything
in `apps.core` related to languages.

## Context

Dristi serves litigants and advocates who do not all read English. Several
features need a shared notion of "which languages do we support": CMS content
(spec 0018), and later UI localisation, notifications, PDF templates and OCR.

That shared notion belongs in `apps.core`, not in any one feature app, so
consumers can import it without depending on each other. This spec introduces
the `Language` model (with per-language capability flags), its admin, a public
read API listing supported languages, and the request-language resolver used
by language-aware endpoints.

## Goals

- A `Language` model in `apps.core.models`, managed in admin — no deploy needed
  to add or withdraw a language.
- Per-language capability metadata (`supports`: UI, translation, OCR, …).
- One default (fallback) language, enforced at the database level.
- A public, read-only, paginated API listing active languages, filterable by
  capability (pagination per spec 0000 section 11).
- A single resolver, `apps.core.languages.resolve_request_language`, that maps
  a request (`lang` query parameter, `Accept-Language` header) to a `Language`.
- Follow the repository API conventions (`spec/0000-api-coding-spec.md`).

## Non-goals

- Translating API error messages or other non-CMS responses. Django's
  `LocaleMiddleware` is **not** enabled; language selection applies only to
  content served by language-aware endpoints.
- Localised UI strings, notification/PDF templates or OCR pipelines themselves
  (each is a separate feature spec; they consume this model).
- Right-to-left layout hints (none of the initial languages need them).
- A write API for languages (admin only).

## Proposed changes

### 1. Data model

Supported languages are stored as rows, not an enum, so a new language can be
added (or temporarily withdrawn) from admin without a code change or deploy.
The set is small and read on every language-aware request, so its table is
cachalot-cached (section 2).

Model: `apps.core.models.Language` (table `core_language`). Languages are
shared reference data, not CMS content: notifications, PDF templates or error
copy may need them later, so the model, its admin and its read API live in
`apps.core`. CMS (spec 0018) is one consumer and imports it; nothing in
`apps.core` imports cms.

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
`["ui", "ocr"]`) and filtered with `supports__contains=<value>`. That lookup
is PostgreSQL-only (Django raises `NotSupportedError` on SQLite), which is
fine because CI runs the test suite on PostgreSQL, as in production
(`.github/workflows/ci.yml`); tests that filter on `supports` therefore need
`DATABASE_URL` pointing at PostgreSQL when run locally. The enum is
deliberately a code-level `TextChoices` (not rows): capabilities are features
of the product, so adding one is a code change anyway; languages remain admin-managed rows.

`supports` is capability metadata for clients and other features (a UI
switcher lists `ui` languages, an OCR pipeline checks `ocr`). It does **not**
gate language resolution — that is driven by `is_active` (section 5); admins
keep the two consistent.

Model `Meta`:

- `ordering = ("sort_order", "code")`
- `UniqueConstraint(fields=["is_default"], condition=Q(is_default=True), name="core_language_single_default")`
- `CheckConstraint(condition=Q(is_default=False) | Q(is_active=True), name="core_language_default_is_active")`
  (`condition=` needs Django 5.1+; this spec requires Django 5.2.17+, see Dependencies)

Validation and behaviour:

- `code` is lowercased in `clean()` and `save()`, so `en-IN` and `en-in` cannot coexist.
- `supports` must be a list of distinct valid `LanguageSupport` values;
  `clean()` rejects unknown values and non-list input, and normalises to enum
  order (deduped) on save, so `["ocr", "ui", "ui"]` is stored as
  `["ui", "ocr"]`.
- The default language cannot be deactivated or deleted; deleting it is
  blocked by a model check and by `on_delete=PROTECT` from consumers such as
  `apps.cms.models.PageTranslation` (spec 0018).
- `Language.objects.get_default()` returns the default row; it is a
  configuration error (`ImproperlyConfigured`) if none exists.

### 2. Cacheability

`Language` is read-mostly and should be cachalot-cacheable:

- Add table `core_language` to `CACHALOT_ONLY_CACHABLE_TABLES` (the `core` app
  as a whole stays uncached, per the comment in `base.py`).
- Do **not** add a manual per-view cache initially.
- Rely on cachalot automatic invalidation on writes.

Test expectations:

- repeated language list and resolver queries should hit cache,
- writes to `Language` should invalidate relevant querysets.

### 3. Admin

Register `Language` in `apps.core.admin` (`LanguageAdmin`):

- list display: `code`, `name`, `native_name`, `supports`, `is_default`, `is_active`, `sort_order`
- list editable: `sort_order`, `is_active`
- list filter: `is_active`, and a `supports` filter (capability membership via `supports__contains`)
- search fields: `code`, `name`, `native_name`
- `supports` is edited with a `MultipleChoiceField` + `CheckboxSelectMultiple`
  in the admin form (choices from `LanguageSupport`), mapped to the JSON list
- read-only audit fields from `BaseModel`
- deactivating or un-defaulting the only default language is rejected with a form error

### 4. API surface (read-only)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/languages/` | List of active supported languages (paginated). |

Notes:

- Read-only in v1; languages are managed in admin.
- Swagger tag: `Core` (inferred from the owning app per spec 0000 section 10.2).
- Public: `permission_classes = [AllowAny]`, overriding the project default
  authenticated permissions.
- The endpoint itself takes no language selection — it lists the choices.

#### 4.1 List behavior

- Returns active languages only, ordered by `sort_order`, then `code`.
- Optional `?supports=<capability>` filter (validated with a DRF `ChoiceField`
  over `LanguageSupport` via a filter serializer, as in the organizations
  app): restricts the list to languages that declare that capability
  (`supports__contains`). An invalid value fails validation with `E00005`
  (`field: "supports"`); no new error code is needed.
- Paginated with the project standard (spec 0000 section 11): DRF page-number
  pagination via `APIListMixin`, the shared `PAGE_SIZE` (20) and `?page=N`.
  The response uses the standard shape `{"count", "next", "previous",
  "results", "meta"}`; the small size of the language set is not a justified
  exception to the pagination standard.

### 5. Language resolution

Every language-aware endpoint (CMS pages today) resolves one **requested
language** per request, from the first source that yields an active language:

1. `lang` query parameter, e.g. `?lang=ml`. Matched case-insensitively against
   active `Language.code`. If present but not an active language code, the
   request fails with `400` and `E10001` (`field: "lang"`). An explicit choice
   is never silently ignored.
2. `Accept-Language` request header. Parsed per RFC 9110 with quality values;
   for each tag in descending `q` order, try an exact match, then its primary
   subtag (`en-IN` → `en`). Unknown or malformed tags are skipped, never an
   error, because browsers send arbitrary values.
3. The default language.

The resolver is a single function used by all language-aware endpoints:

```python
# apps/core/languages.py
def resolve_request_language(request) -> Language: ...
```

What happens with the resolved language — translation lookup, fallback to the
default language, `Content-Language` / `Vary: Accept-Language` headers — is
defined by the consuming spec (spec 0018 section 6.1 for CMS pages).

The `lang` parameter is declared in OpenAPI by each consuming endpoint
(`OpenApiParameter("lang", str, OpenApiParameter.QUERY, ...)`), with the
`E10001` example attached via `error_responses(...)`.

### 6. Serializer contract

`apps.core.serializers.LanguageSerializer` fields:

- `code`
- `name`
- `native_name`
- `is_default`
- `supports`

Read-only. `id`, `sort_order` and `is_active` are not exposed: clients address
languages by `code`, receive them already ordered, and only see active ones.

### 7. API examples

#### 7.1 List supported languages

`GET /api/v1/languages/`

```json
{
  "count": 3,
  "next": null,
  "previous": null,
  "results": [
    {"code": "en", "name": "English", "native_name": "English", "is_default": true, "supports": ["ui"]},
    {"code": "ml", "name": "Malayalam", "native_name": "മലയാളം", "is_default": false, "supports": ["ui"]},
    {"code": "hi", "name": "Hindi", "native_name": "हिन्दी", "is_default": false, "supports": ["ui"]}
  ],
  "meta": {
    "timestamp": "2026-10-13T12:30:00+05:30",
    "app_version": "<git-sha>",
    "spec_version": "1.0"
  }
}
```

#### 7.2 Unsupported language

`GET /api/v1/cms/pages/slug/terms/?lang=xx` → `400` (raised by the resolver,
illustrated on a CMS endpoint)

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

### 8. Error codes

Allocate domain `10` → `core` in `apps.api.errors.DOMAINS` and in the table in
spec 0000 section 9.2. Define codes in `src/apps/core/errors.py`:

| Code | Status | Default message | When |
|---|---|---|---|
| `E10001` | 400 | `Language is not supported.` | `lang` query parameter is not an active language code (`field: "lang"`). |

### 9. URL routing and wiring

In `src/apps/api/urls.py`, register `languages` on the existing router
(`apps.core.views.LanguageViewSet`, list only, `basename="language"`), next to
`api-version-changelogs`. The endpoint is core-owned, so it does not live under
any feature-app prefix.

### 10. Migrations and seed data

1. `core/0007_language` — create `apps.core.models.Language` (including
   `supports`) and its constraints.
2. `core/0008_seed_languages` (data migration, reversible) — seed the languages
   below.

| `code` | `name` | `native_name` | `is_default` | `sort_order` | `is_active` | `supports` |
|---|---|---|---|---|---|---|
| `en` | English | English | yes | 0 | yes | `["ui"]` |
| `ml` | Malayalam | മലയാളം | no | 10 | yes | `["ui"]` |
| `hi` | Hindi | हिन्दी | no | 20 | yes | `["ui"]` |

All seeded languages declare only `ui` at first; `translation` and `ocr` are
added later from admin as those capabilities actually ship for a language.

Seeding uses `update_or_create(code=...)` so it is idempotent.

### 11. Tests

Add model and API tests covering at least:

1. `Language`: code validator accepts `en`, `ml`, `en-in`, rejects `EN_IN`, `e`, `en-`, `en\n`; code is lowercased on save; only one default allowed; default cannot be inactive or deleted.
2. `supports` accepts only known `LanguageSupport` values, rejects duplicates
   and non-list input, and is normalised to enum order on save.
3. `GET /api/v1/languages/` is public, paginated with the standard shape
   (`count`, `next`, `previous`, `results` + `meta`), returns only active
   languages in `sort_order`, and exposes exactly `code`, `name`,
   `native_name`, `is_default`, `supports`.
4. `?supports=ui` returns only languages declaring `ui`; `?supports=bogus`
   returns `400` with code `E00005` and field `supports`.
5. Resolution order: `lang` beats `Accept-Language`; `Accept-Language` beats the default; `q` values are honoured; `en-IN` matches `en`; unknown or malformed `Accept-Language` falls back to the default without error.
6. `?lang=xx` and `?lang=<inactive code>` return `400` with code `E10001` and field `lang`.
7. cachalot behavior for language reads + invalidation on `Language` writes.
8. Seeded languages are present with the codes, flags and `supports` values above.
9. Schema contains the `Core` tag and `/api/v1/languages/`.

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

## Dependencies

- Django 5.2.17+ (upgraded in a separate PR). Implementation must not start on
  the current Django 5.0 pin: `CheckConstraint(condition=...)` (section 1)
  does not exist before 5.1.
- CI tests running on PostgreSQL (separate PR): `supports__contains`
  (sections 1, 3 and 4.1) is not supported on SQLite.

## Open questions

- Should consumers prefer languages with a specific capability (for example
  `translation` in `supports`) over merely `is_active` ones when resolving
  content? For now `supports` is informational only.
- Should `hi` be active from day one, or seeded inactive until content is translated?
- Should RTL script support be added to `supports` (or a separate flag) before
  a right-to-left language is introduced?

## Related specs

- `0000-api-coding-spec.md` — API conventions, response metadata, error codes, schema, testing.
- `0002-audit-fields-base-model.md` — base audited model behavior.
- `0006-active-flag-model.md` — `is_active` mixin used by `Language`.
- `0012-redis-caching.md` — cachalot-based cache strategy.
- `0018-cms-pages.md` — first consumer: localised CMS pages and language fallback.
