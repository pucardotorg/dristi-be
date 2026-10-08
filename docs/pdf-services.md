# PDF Service (`apps.pdf`) — usage and end-to-end testing guide

This guide covers the PDF Service implemented for
[spec 0016](../spec/0016-pdf-services.md): how to configure document templates,
every API with request/response samples, and the exact data to insert (through
the Django admin) to exercise the full flow end to end.

Contents:

1. [How it works](#1-how-it-works)
2. [Prerequisites](#2-prerequisites)
3. [Data to insert from the admin](#3-data-to-insert-from-the-admin)
4. [Authentication for API calls](#4-authentication-for-api-calls)
5. [API reference with samples](#5-api-reference-with-samples)
6. [End-to-end test walkthrough](#6-end-to-end-test-walkthrough)
7. [Configuration reference](#7-configuration-reference)
8. [Signing primitives (used by eSign)](#8-signing-primitives-used-by-esign)
9. [Error codes](#9-error-codes)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. How it works

```text
caller ──POST /api/v1/pdf/jobs/──> PDFJob (QUEUED) ──Dramatiq "pdf" queue──> worker
                                                                              │
     PDFTemplateVersion.format_config + data_config  <── loaded (cached) ─────┤
     DataMapper: direct / external_api / derived / format /                   │
                 localization / image / qr          ── builds render context ─┤
     composer + reportlab renderer                  ── PDF bytes ─────────────┤
     apps.files.upload_file()                       ── file_id ───────────────┤
                                                                              ▼
caller <──GET /api/v1/pdf/jobs/{id}/ (poll) ── PDFJob COMPLETED, file_ids=[...]
caller <──GET /api/v1/pdf/jobs/{id}/download/ ── application/pdf (streamed from apps.files)
```

* **Templates are data, not code.** A `PDFTemplate` is a document type with a
  stable `key`; a `PDFTemplateVersion` holds its `format_config` (layout) and
  `data_config` (how request data fills the layout). A new version takes effect
  for new jobs immediately — no restart.
* **Generation is asynchronous.** `POST /jobs/` returns `202` with a job id;
  a Dramatiq worker renders the PDF and stores it through `apps.files`.
  Only the returned `file_id` is kept on the job.
* **Identical requests are not regenerated.** A completed job is reused when
  tenant, key, entity, template version and the *significant* request fields
  all match (`200`, `"reused": true`).
* **Small documents can be rendered synchronously** with `POST /render/`
  (bytes returned, nothing stored, no job).
* **Bulk** templates split a list of records into chunks, render chunks in
  parallel, and optionally merge them into one PDF.

Models (all visible in the Django admin under **PDF**):

| Model | Purpose |
| --- | --- |
| `PDFTemplate` | Document type: `key`, `name`, `description`, `is_active` |
| `PDFTemplateVersion` | `template`, `version` (auto), `format_config`, `data_config`, `is_active` (one active per template) |
| `PDFJob` | A generation request: status, `file_ids`, counts, errors, timestamps (read-only in admin) |
| `PDFJobRecord` | One bulk chunk of a job (read-only in admin) |

Job status lifecycle: `QUEUED → PROCESSING → COMPLETED | PARTIAL_SUCCESS | FAILED`,
and `QUEUED/PROCESSING → CANCELLED`. (`CREATED` exists for completeness; the API
moves new jobs straight to `QUEUED`.)

---

## 2. Prerequisites

1. **Migrations applied** (`apps.pdf` ships migration `0001_initial`).
2. **A Dramatiq worker running.** Jobs are processed only by a worker. With
   the dev compose stack the `worker` service runs
   `python manage.py rundramatiq`, which consumes every queue including `pdf`.
   Without a worker, jobs stay `QUEUED` forever.
3. **Redis** (broker + cache) and **file storage** (local filesystem or the
   S3/rustfs bucket) configured as for `apps.files`.
4. **A system user for background uploads (recommended).** Generated PDFs are
   attributed to the requesting user. When a job has no requesting user, the
   worker uses `FILE_SYSTEM_USER_ID` (see [§3.1](#31-system-user-optional-but-recommended)).
   If neither exists the job fails with `PDF_INVALID_CONFIG`.
5. **Python dependencies** from `src/requirements/base.txt`: `reportlab`,
   `pypdf`, `pyhanko`, `qrcode`, `pillow`, `jsonpath-ng`, `uharfbuzz`
   (Indic text shaping) and `fonttools` (signature appearance fonts). Rebuild
   the image after pulling.

---

## 3. Data to insert from the admin

Log in to `/admin/` as a superuser. Everything below can be entered through
the admin forms; JSON fields accept the JSON exactly as shown.

### 3.1 System user (optional but recommended)

**Users → Users → Add**

| Field | Value |
| --- | --- |
| Mobile number | `+919000000999` |
| Name | `Dristi System` |
| Email | `system@dristi.internal` |
| Registration status | `COMPLETE` |
| Active | ✔ |

Then set in `.env`: `FILE_SYSTEM_USER_ID=system@dristi.internal` (an email,
a `+91…` mobile number, or the user's primary key are all accepted).

### 3.2 API test user

Any user with **Registration status = COMPLETE** and a password can call the
APIs. The admin superuser works (superusers are created `COMPLETE`), and staff
users see every job; non-staff users see only their own jobs. To test
per-user visibility, create a second normal user, e.g.:

| Field | Value |
| --- | --- |
| Mobile number | `+919876543210` |
| Name | `PDF Tester` |
| Password | set via the admin "change password" form |
| Registration status | `COMPLETE` |

### 3.3 Template 1 — `case-summons` (single document, all mapping types)

Exercises every mapping type except `external_api` (which needs a live
service; see [§7.3](#73-external_api-mapping)), plus tables, lists, conditional
blocks, localization (English + Malayalam), an embedded image, a QR code,
headers/footers and page numbers.

**PDF → PDF templates → Add**

| Field | Value |
| --- | --- |
| Key | `case-summons` |
| Name | `Case summons` |
| Description | `Summons issued to a respondent` |
| Is active | ✔ |

**PDF → PDF template versions → Add**

| Field | Value |
| --- | --- |
| Template | `case-summons` |
| Is active | ✔ |
| Format config | JSON below |
| Data config | JSON below |

`format_config`:

```json
{
  "page": {
    "size": "A4",
    "orientation": "portrait",
    "margins": {"top": 48, "right": 48, "bottom": 48, "left": 48}
  },
  "metadata": {"title": "{{ title }} - {{ case_number }}", "author": "Dristi", "subject": "Summons"},
  "styles": {
    "default": {"font": "noto-sans", "size": 11},
    "court": {"size": 14, "bold": true, "align": "center", "space_after": 2},
    "muted": {"size": 9, "color": "#555555"}
  },
  "header": {"left": "{{ court_name }}", "right": "Page {page} of {pages}", "line": true},
  "footer": {"left": "Ref: {{ case_number }}", "right": "Generated {{ generated_on }}", "line": true},
  "body": [
    {"type": "paragraph", "text": "{{ court_name }}", "style": "court"},
    {"type": "heading", "text": "{{ title }}", "level": 1, "align": "center"},
    {"type": "paragraph", "text": "{{ title_ml }}", "align": "center", "style": "muted"},
    {"type": "line"},
    {"type": "paragraph", "text": "Case number: <b>{{ case_number }}</b>"},
    {"type": "paragraph", "text": "Case type: {{ case_type_label }}"},
    {
      "type": "paragraph",
      "text": "To: <b>{{ respondent_name }}</b><br/>{{ data.respondent.address | nl2br }}"
    },
    {
      "type": "paragraph",
      "text": "You are hereby summoned to appear before this Court on <b>{{ hearing_date }}</b> at {{ data.hearing.time }} in {{ data.hearing.hall }}."
    },
    {"type": "paragraph", "text": "Court fee: Rs. {{ fee_text }}", "when": "data.fee"},
    {"type": "heading", "text": "Witnesses", "level": 3, "when": "witnesses"},
    {
      "type": "table",
      "source": "witnesses",
      "as": "w",
      "when": "witnesses",
      "header_background": "#eeeeee",
      "columns": [
        {"header": "#", "value": "{{ loop.index }}", "width": 30, "align": "center"},
        {"header": "Name", "value": "{{ w.name }}"},
        {"header": "Age", "value": "{{ w.age }}", "width": 50, "align": "right"},
        {"header": "Address", "value": "{{ w.address }}", "width": "40%"}
      ]
    },
    {"type": "heading", "text": "Documents to produce", "level": 3, "when": "documents"},
    {
      "type": "list",
      "source": "documents",
      "as": "d",
      "item": "{{ d }}",
      "ordered": true,
      "when": "documents"
    },
    {"type": "spacer", "height": 18},
    {"type": "paragraph", "text": "Witnesses listed: {{ witness_count }}", "style": "muted"},
    {"type": "image", "source": "court_seal", "width": 70, "align": "left"},
    {"type": "qr", "source": "verify_qr", "size": 90, "align": "right"},
    {
      "type": "paragraph",
      "text": "Scan to verify this summons.",
      "align": "right",
      "style": "muted"
    }
  ]
}
```

`data_config`:

```json
{
  "mappings": [
    {"type": "direct", "target": "case_number", "path": "$.case.number", "transform": "upper"},
    {
      "type": "direct",
      "target": "case_type_label",
      "path": "$.case.type",
      "labels": {"CC": "Calendar Case", "OS": "Original Suit", "CRL": "Criminal Case"},
      "default": "Other"
    },
    {
      "type": "direct",
      "target": "court_name",
      "path": "$.court.name",
      "default": "District Court"
    },
    {
      "type": "direct",
      "target": "respondent_name",
      "path": "$.respondent.name",
      "transform": "title"
    },
    {
      "type": "direct",
      "target": "witnesses",
      "path": "$.witnesses[*]",
      "columns": {"name": "$.name", "age": "$.age", "address": "$.address"}
    },
    {"type": "direct", "target": "documents", "path": "$.documents[*]", "many": true},
    {"type": "derived", "target": "witness_count", "expression": "witnesses | length"},
    {"type": "derived", "target": "generated_on", "function": "today"},
    {
      "type": "format",
      "target": "hearing_date",
      "source": "data.hearing.date",
      "format": "date",
      "pattern": "%d %B %Y"
    },
    {
      "type": "format",
      "target": "fee_text",
      "source": "data.fee",
      "format": "number",
      "decimals": 2,
      "grouping": "indian",
      "required": false
    },
    {"type": "localization", "target": "title", "code": "SUMMONS_TITLE"},
    {"type": "localization", "target": "title_ml", "code": "SUMMONS_TITLE", "locale": "ml_IN"},
    {
      "type": "image",
      "target": "court_seal",
      "source": "data.court.seal_base64",
      "source_type": "base64",
      "max_width": 300,
      "on_error": "placeholder"
    },
    {
      "type": "qr",
      "target": "verify_qr",
      "template": "https://dristi.example.gov.in/verify/{{ case_number }}"
    }
  ],
  "localization": {
    "module": "pdf-summons",
    "messages": {"en_IN": {"SUMMONS_TITLE": "SUMMONS"}, "ml_IN": {"SUMMONS_TITLE": "സമൻസ്"}}
  },
  "significant_fields": ["$.case.number", "$.respondent", "$.hearing", "$.witnesses"],
  "request_schema": {
    "type": "object",
    "required": ["case", "respondent", "hearing"],
    "properties": {
      "case": {"type": "object", "required": ["number"]},
      "respondent": {"type": "object", "required": ["name"]},
      "hearing": {"type": "object", "required": ["date"]}
    }
  },
  "filename": "summons-{{ case_number | replace('/', '-') }}"
}
```

### 3.4 Template 2 — `bulk-notice` (bulk, chunked and merged)

Every record of `data.records` becomes one page; 2 records per chunk, chunks
merged into one PDF when all succeed. In bulk templates, `data` is the
*current record* and `request` is the *whole request payload*.

**PDF templates → Add**: Key `bulk-notice`, Name `Bulk notice`, Is active ✔.

**PDF template versions → Add** (template `bulk-notice`, Is active ✔):

`format_config`:

```json
{
  "page": {"size": "A4"},
  "header": {"left": "{{ request.court }}", "right": "Page {page} of {pages}", "line": true},
  "body": [
    {"type": "heading", "text": "NOTICE", "level": 1, "align": "center"},
    {"type": "paragraph", "text": "Notice No. <b>{{ notice_no }}</b>"},
    {"type": "paragraph", "text": "To: <b>{{ data.name }}</b>, {{ data.address }}"},
    {
      "type": "paragraph",
      "text": "You are required to appear on {{ appear_on }} in case {{ request.case_number }}."
    }
  ]
}
```

`data_config`:

```json
{
  "mappings": [
    {
      "type": "derived",
      "target": "notice_no",
      "expression": "request.case_number ~ '/' ~ data.number"
    },
    {
      "type": "format",
      "target": "appear_on",
      "source": "request.hearing_date",
      "format": "date",
      "pattern": "%d-%m-%Y"
    }
  ],
  "bulk": {
    "records_path": "$.records",
    "merge": true,
    "merge_partial": false,
    "max_records_per_document": 2
  },
  "significant_fields": ["$.case_number", "$.records"]
}
```

### 3.5 Template 3 — `filing-receipt` (synchronous render)

A small document meant for `POST /api/v1/pdf/render/`.

**PDF templates → Add**: Key `filing-receipt`, Name `Filing receipt`, Is active ✔.

**PDF template versions → Add** (template `filing-receipt`, Is active ✔):

`format_config`:

```json
{
  "page": {"size": "A5", "orientation": "landscape"},
  "body": [
    {"type": "heading", "text": "Filing Receipt", "level": 2, "align": "center"},
    {"type": "paragraph", "text": "Receipt for {{ data.party }} - amount Rs. {{ amount }}"},
    {"type": "qr", "value": "receipt:{{ data.receipt_no }}", "size": 70, "align": "right"}
  ]
}
```

`data_config`:

```json
{
  "mappings": [
    {
      "type": "format",
      "target": "amount",
      "source": "data.amount",
      "format": "number",
      "decimals": 2,
      "grouping": "indian"
    }
  ],
  "sync_render": true
}
```

### 3.6 Admin behaviour to be aware of

* **Version numbers are assigned automatically** (1, 2, 3 … per template);
  leave the field empty.
* **Saving a version with *Is active* ticked deactivates the template's other
  versions.** To roll back, tick *Is active* on an older version and save.
* **Configuration is validated on save.** Unknown block/mapping types, unknown
  keys, invalid Jinja syntax, invalid JSONPath, unknown fonts, duplicate or
  reserved mapping targets (`data`, `meta`, `record`, `records`, `loop`) are
  rejected with a message pointing at the offending path, e.g.
  `body/3/text: unexpected '}'`.
* **A version used by a job is immutable.** Its `format_config`/`data_config`
  can no longer be edited (you can still toggle *Is active*). Create a new
  version instead; the version number is part of the reuse key, so the next
  request regenerates the document.
* **Unticking *Is active* on a template** makes its key unavailable for new
  jobs (`404 PDF_TEMPLATE_NOT_FOUND`); existing jobs remain downloadable.
* **Jobs and job records are read-only** in the admin (inspect status,
  `error_code`, `error_message`, `file_ids`, per-chunk records). Generated
  files are visible under **Files → Files** with tags `pdf`, the template key
  and the entity id.

---

## 4. Authentication for API calls

All PDF endpoints require an authenticated user whose registration is
`COMPLETE` (project default, spec 0000 §6). Authentication is session-cookie
based:

1. `POST /api/v1/sessions/` with `{"mobile_number": "+919876543210", "password": "<password>"}`.
   The response sets the `sessionid` and `csrftoken` cookies.
2. Send both cookies on every later request, and for `POST`/`DELETE` also send
   the header `X-CSRFToken: <value of the csrftoken cookie>`.

Postman / Bruno / Insomnia handle cookies automatically; just add the
`X-CSRFToken` header. Alternatively, log in to `/admin/` in the browser and use
the Swagger UI at `/api/docs/` (tag **pdf**), which reuses the admin session.

Optional request header: `X-Correlation-Id: <id>` — stored on the job and
forwarded to external APIs and localization calls, and written to log lines.

Every JSON response carries the standard `meta` envelope:

```json
"meta": {"timestamp": "2026-10-08T15:30:00.123456+05:30", "app_version": "abc123", "spec_version": "1.0"}
```

Error responses have the shape `{"detail": "...", "code": "PDF_...", "meta": {...}}`
(DRF field validation errors keep the usual per-field shape).

---

## 5. API reference with samples

Base path: `/api/v1/pdf/`. Swagger: `/api/docs/` → tag **pdf**.

| Method | Path | Purpose | Success |
| --- | --- | --- | --- |
| POST | `/api/v1/pdf/jobs/` | Create a generation job (or reuse one) | `202` / `200` |
| GET | `/api/v1/pdf/jobs/` | Search jobs (`entity_id`, `key`, `tenant_id`, `status`), paginated | `200` |
| GET | `/api/v1/pdf/jobs/{id}/` | Retrieve one job (poll until `COMPLETED`) | `200` |
| POST | `/api/v1/pdf/jobs/{id}/cancel/` | Cancel a `QUEUED`/`PROCESSING` job | `200` |
| GET | `/api/v1/pdf/jobs/{id}/download/` | Download a generated PDF | `200` (`application/pdf`) |
| DELETE | `/api/v1/pdf/jobs/{id}/` | Delete the job's generated documents | `200` |
| POST | `/api/v1/pdf/render/` | Synchronous render; nothing stored | `200` (`application/pdf`) |

### 5.1 Create a job — `POST /api/v1/pdf/jobs/`

Request body:

| Field | Required | Description |
| --- | --- | --- |
| `key` | yes | Template key, e.g. `case-summons` |
| `tenant_id` | yes | Tenant requesting the document (max 64 chars) |
| `data` | yes | JSON object; the payload the template maps from (max `PDF_MAX_REQUEST_DATA_BYTES`) |
| `entity_id` | no | Business entity the document belongs to (searchable; used in reuse key, tags and filename) |
| `organization_id` | no | UUID of an existing `Organization`; recorded on the stored file |
| `locale` | no | e.g. `en_IN`, `ml_IN`; default `en_IN` for localization lookups |
| `force_regenerate` | no | `true` always creates a new job (default `false`) |

Sample request — single document (`case-summons`):

```json
{
  "key": "case-summons",
  "tenant_id": "kl",
  "entity_id": "CC-123-2026",
  "locale": "en_IN",
  "force_regenerate": false,
  "data": {
    "case": {"number": "cc/123/2026", "type": "CC"},
    "court": {
      "name": "District Court, Ernakulam",
      "seal_base64": "iVBORw0KGgoAAAANSUhEUgAAACgAAAAoCAIAAAADnC86AAAA1ElEQVR42u2YWw6FIAxEZXI3y4pcLvfPGHk4g21KjH4aZw4tpYCplLJFPNiCnp8q2FNqvs9i5hKZ6h5vegT3YB4p4eFBZYTdiNW5VL9vg5suzOTxwga4FqsVyzjAqkpVCcaDzbN97SKscwAPKsOGYYYlEzxfsnNFB79wx1ZhuxPqJGTrHfpseICiI/7AH/h94OZS8+iUB2ixVBsG3bOCX6cc906YH2xJE0jnlSfUiznUs5IJlarqCTYjWelAH3mFMamvcYZgfo0ghQtfzIN/RbxnP/4D85uWI3uyTcsAAAAASUVORK5CYII="
    },
    "respondent": {"name": "ravi kumar", "address": "12, MG Road\nKochi 682011"},
    "hearing": {"date": "2026-11-05", "time": "10:30 AM", "hall": "Court Hall 3"},
    "fee": 1250.5,
    "witnesses": [
      {"name": "Anitha Menon", "age": 42, "address": "Aluva"},
      {"name": "Joseph Thomas", "age": 35, "address": "Kakkanad"}
    ],
    "documents": ["Original sale deed", "Bank statement (2025-26)"],
    "requested_at": "2026-10-08T10:00:00Z"
  }
}
```

> `seal_base64` is a 40×40 PNG (a red ring) so the image mapping can be tested
> without a network call. Any PNG/JPEG base64 string or `data:image/...;base64,`
> URI works.

Response `202 Accepted` (new job):

```json
{
  "id": "1dfc4d94-2bd8-4dfe-ba4c-abda21a698b4",
  "key": "case-summons",
  "template_version": 1,
  "tenant_id": "kl",
  "entity_id": "CC-123-2026",
  "organization_id": null,
  "status": "QUEUED",
  "is_bulk": false,
  "file_ids": [],
  "total_count": 1,
  "completed_count": 0,
  "failed_count": 0,
  "error_code": "",
  "error_message": "",
  "reused": false,
  "records": [],
  "queued_at": "2026-10-08T09:18:33.439593Z",
  "started_at": null,
  "completed_at": null,
  "files_deleted_at": null,
  "created_at": "2026-10-08T09:18:33.439031Z",
  "updated_at": "2026-10-08T09:18:33.439031Z",
  "meta": {"timestamp": "2026-10-08T14:48:33.441000+05:30", "app_version": "unknown", "spec_version": "1.0"}
}
```

Response `200 OK` (an equivalent completed job exists and `force_regenerate`
is `false`): the existing job, with `"reused": true` and its `file_ids`.
Changing only non-significant fields (here `requested_at`) still reuses;
changing e.g. `hearing.date` creates a new job.

Sample request — bulk (`bulk-notice`):

```json
{
  "key": "bulk-notice",
  "tenant_id": "kl",
  "entity_id": "CC-123-2026",
  "data": {
    "court": "District Court, Ernakulam",
    "case_number": "CC/123/2026",
    "hearing_date": "2026-11-05",
    "records": [
      {"number": 1, "name": "Ravi Kumar", "address": "Kochi"},
      {"number": 2, "name": "Anitha Menon", "address": "Aluva"},
      {"number": 3, "name": "Joseph Thomas", "address": "Kakkanad"},
      {"number": 4, "name": "Meera Nair", "address": "Thrissur"},
      {"number": 5, "name": "Suresh Babu", "address": "Kollam"}
    ]
  }
}
```

Response `202` with `"is_bulk": true` and `"total_count": 5` (records, not
chunks).

Error responses:

| Status | `code` | When |
| --- | --- | --- |
| 400 | (field errors) | Missing `key`/`tenant_id`/`data`, `data` not an object, unknown `organization_id`, oversized `data` |
| 400 | `PDF_INVALID_REQUEST_DATA` | `data` fails the template's `request_schema`, or a bulk request has no records |
| 403 | — | Not logged in, registration incomplete, or missing CSRF header |
| 404 | `PDF_TEMPLATE_NOT_FOUND` | Unknown/inactive key, or template has no active version |

Example `400` (summons without `hearing`):

```json
{"detail": "Request data is invalid: (root): 'hearing' is a required property", "code": "PDF_INVALID_REQUEST_DATA", "meta": {...}}
```

### 5.2 Search jobs — `GET /api/v1/pdf/jobs/`

Query parameters (all optional, ANDed): `entity_id`, `key`, `tenant_id`,
`status` (`QUEUED`, `PROCESSING`, `COMPLETED`, `PARTIAL_SUCCESS`, `FAILED`,
`CANCELLED`, `CREATED`), `page`.

```text
GET /api/v1/pdf/jobs/?entity_id=CC-123-2026&status=COMPLETED
```

Response `200` — standard page-number pagination (20 per page), newest first;
list items omit `records`:

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {"id": "261a20b4-…", "key": "bulk-notice", "status": "COMPLETED", "is_bulk": true, "file_ids": ["a446aa57-…"], "total_count": 5, "completed_count": 5, "failed_count": 0, "…": "…"},
    {"id": "1dfc4d94-…", "key": "case-summons", "status": "COMPLETED", "is_bulk": false, "file_ids": ["9b0c…"], "total_count": 1, "…": "…"}
  ],
  "meta": {"…": "…"}
}
```

Non-staff users only see jobs they created; staff/superusers see all.
An invalid `status` returns `400`.

### 5.3 Retrieve a job — `GET /api/v1/pdf/jobs/{id}/`

Poll until `status` is terminal (`COMPLETED`, `PARTIAL_SUCCESS`, `FAILED`,
`CANCELLED`). Bulk jobs include per-chunk `records`:

```json
{
  "id": "261a20b4-c87e-4381-87ff-eaa1f0abc6ce",
  "key": "bulk-notice",
  "template_version": 1,
  "status": "COMPLETED",
  "is_bulk": true,
  "file_ids": ["a446aa57-aeac-4ed6-b32c-5c8b8e246b0f"],
  "total_count": 5,
  "completed_count": 5,
  "failed_count": 0,
  "records": [
    {"sequence": 0, "status": "COMPLETED", "count": 2, "file_id": "…", "error_code": "", "error_message": ""},
    {"sequence": 1, "status": "COMPLETED", "count": 2, "file_id": "…", "error_code": "", "error_message": ""},
    {"sequence": 2, "status": "COMPLETED", "count": 1, "file_id": "…", "error_code": "", "error_message": ""}
  ],
  "…": "…"
}
```

A failed job reports a sanitized reason, e.g.
`"status": "FAILED", "error_code": "PDF_INVALID_REQUEST_DATA", "error_message": "Required value for 'case_number' is missing."`.
A partially successful bulk job reports
`"status": "PARTIAL_SUCCESS", "error_code": "PDF_BULK_PARTIAL", "error_message": "2 of 5 records failed."`.

Another user's job returns `404`.

### 5.4 Cancel — `POST /api/v1/pdf/jobs/{id}/cancel/`

No body. Cancels a `QUEUED`/`PROCESSING` job: pending bulk chunks are cancelled,
running chunks finish but their output is discarded, and any document already
stored for the job is deleted from `apps.files`.

* `200` — job with `"status": "CANCELLED"`.
* `409` — `{"detail": "A COMPLETED job cannot be cancelled.", "code": "PDF_INVALID_TRANSITION", …}`.

### 5.5 Download — `GET /api/v1/pdf/jobs/{id}/download/`

Streams the PDF from the File Storage Service.

| Query | Meaning |
| --- | --- |
| *(none)* | First document (`file_ids[0]`) — the only one for single jobs, the merged one for merged bulk jobs |
| `index=N` | `file_ids[N]` — for unmerged bulk jobs (one file per chunk) |
| `sequence=N` | The document of bulk chunk `N` (works even when merged) |

`index` and `sequence` are mutually exclusive (`400`).

Response `200`, `Content-Type: application/pdf`,
`Content-Disposition: attachment; filename="case-summons-CC-123-2026.pdf"`
(`-part-N` is appended for chunks/indexes of multi-file jobs).

`404 PDF_NO_DOCUMENT` — job not completed yet, documents deleted, or unknown
index/sequence.

> The *stored* file name in `apps.files` follows the template's
> `data_config.filename` (e.g. `summons-CC-123-2026.pdf`); the download name
> is derived from key + entity id.

### 5.6 Delete documents — `DELETE /api/v1/pdf/jobs/{id}/`

Deletes every document the job produced (via `apps.files.delete_file`), keeps
the job row for audit, clears `file_ids`, and sets `files_deleted_at`.
A job whose documents were deleted is never reused.

* `200` — the job with `"file_ids": []` and `"files_deleted_at": "…"`.
* `409 PDF_JOB_ACTIVE` — the job is still `QUEUED`/`PROCESSING`; cancel first.
* `409 PDF_INVALID_TRANSITION` — storage could not delete some files; the
  remaining ids stay on the job, retry later.

### 5.7 Synchronous render — `POST /api/v1/pdf/render/`

Body: `key`, `tenant_id`, `data`, optional `locale`. Returns the PDF bytes
directly; **no job row and no stored file**.

```json
{
  "key": "filing-receipt",
  "tenant_id": "kl",
  "locale": "en_IN",
  "data": {"party": "Ravi Kumar", "amount": 150000, "receipt_no": "R-2026-0001"}
}
```

Response `200`, `Content-Type: application/pdf`,
`Content-Disposition: inline; filename="filing-receipt.pdf"`.

Rejected with `400 PDF_SYNC_RENDER_NOT_ALLOWED` for bulk templates, templates
with any `external_api` mapping, or `data_config.sync_render: false`.
`504 PDF_SYNC_RENDER_TIMEOUT` when rendering exceeds
`PDF_SYNC_RENDER_TIMEOUT_SECONDS`. (`case-summons` also works here, since it
has no external API mapping.)

---

## 6. End-to-end test walkthrough

With the data from [§3](#3-data-to-insert-from-the-admin) inserted and a
worker running:

| # | Step | Expected |
| --- | --- | --- |
| 1 | `POST /api/v1/sessions/` as the test user | `200`, cookies set |
| 2 | `POST /api/v1/pdf/jobs/` with the `case-summons` sample | `202`, `status: QUEUED`, note `id` |
| 3 | `GET /api/v1/pdf/jobs/{id}/` until terminal (usually < 2 s) | `status: COMPLETED`, one `file_ids` entry |
| 4 | `GET /api/v1/pdf/jobs/{id}/download/` | A 1-page A4 PDF: court name, "SUMMONS" + "സമൻസ്", case `CC/123/2026`, "Calendar Case", "Ravi Kumar" with a 2-line address, hearing "05 November 2026", fee "1,250.50", witness table, numbered document list, red seal, QR code, header `Page 1 of 1`, footer with today's date |
| 5 | Admin → **Files → Files** | A `PDF` file `summons-CC-123-2026.pdf`, tags `pdf`, `case-summons`, `cc-123-2026` (tags are slugified) |
| 6 | Repeat step 2 with only `requested_at` changed | `200`, same `id`, `reused: true` |
| 7 | Repeat step 2 with `"force_regenerate": true` | `202`, new job |
| 8 | Admin: add a **new version** of `case-summons` (same JSON, change e.g. the heading text), then repeat step 2 | `202`, `template_version: 2` (old document is stale) |
| 9 | `GET /api/v1/pdf/jobs/?entity_id=CC-123-2026` | Paginated list incl. the jobs above |
| 10 | `POST /api/v1/pdf/jobs/` with the `bulk-notice` sample | `202`, `is_bulk: true`, `total_count: 5` |
| 11 | Poll the bulk job | `COMPLETED`, `completed_count: 5`, 3 `records`, one merged `file_ids` entry |
| 12 | Download the bulk job; then with `?sequence=1` | 5-page merged PDF ("Notice No. CC/123/2026/1" … "/5"); then the 2-page chunk 2 |
| 13 | `POST /api/v1/pdf/render/` with the `filing-receipt` sample | `200`, A5 landscape PDF, "Rs. 1,50,000.00", QR |
| 14 | `POST /api/v1/pdf/render/` with `"key": "bulk-notice"` | `400 PDF_SYNC_RENDER_NOT_ALLOWED` |
| 15 | `POST /api/v1/pdf/jobs/` for `case-summons` with `data` missing `hearing` | `400 PDF_INVALID_REQUEST_DATA`, no job created |
| 16 | Stop the worker, create a job, `POST …/cancel/`, start the worker | `200 CANCELLED`; the worker skips it, no file stored |
| 17 | `POST …/cancel/` on a completed job | `409 PDF_INVALID_TRANSITION` |
| 18 | `DELETE /api/v1/pdf/jobs/{id}/` on the job from step 2 | `200`, `file_ids: []`, `files_deleted_at` set; file gone from **Files**; download now `404` |
| 19 | Log in as a different non-staff user, `GET` the job from step 2 | `404` |
| 20 | Create a job with `"data": {"case": {"number": "x"}, "respondent": {"name": "x"}, "hearing": {"date": "not-a-date"}}` | Job ends `FAILED`, `error_code: PDF_INVALID_REQUEST_DATA`, not retried |

Extra scenarios:

* **Partial success (bulk)** — create a new version of `bulk-notice` whose
  `data_config.mappings` additionally contains
  `{"type": "direct", "target": "addr", "path": "$.address"}`, then send the
  bulk sample with the `address` key removed from record 3. The chunk holding
  records 3–4 fails (`PDF_INVALID_REQUEST_DATA`, not retried), the job ends
  `PARTIAL_SUCCESS` with `completed_count: 3`, `failed_count: 2`,
  `error_message: "2 of 5 records failed."`, and — because `merge_partial` is
  `false` — `file_ids` holds the two successful chunk files instead of a
  merged file. Set `merge_partial: true` to merge the successful chunks anyway.
* **Image placeholder** — set `seal_base64` to `"not-base64"`: the job fails
  (`PDF_INVALID_REQUEST_DATA`). Placeholders (`on_error: placeholder`) apply to
  *fetch* failures of `url` images, e.g. an unreachable `https://` URL with
  `"source_type": "url"`, which renders a dashed empty box instead.
* **Localization in another locale** — send `"locale": "ml_IN"`: `title`
  becomes "സമൻസ്".

---

## 7. Configuration reference

### 7.1 `format_config` (layout)

Top level (only `body` is required):

| Key | Description |
| --- | --- |
| `page` | `size`: `A3`, `A4` (default), `A5`, `LETTER`, `LEGAL`; `orientation`: `portrait`/`landscape`; `margins`: `top/right/bottom/left` in points (default 56/48/56/48) |
| `metadata` | PDF `title`, `author`, `subject` (templated) |
| `styles` | Named paragraph styles; `default` applies to all. Keys: `font`, `size`, `leading`, `align` (`left/center/right/justify`), `color` (`#rrggbb`), `bold`, `italic`, `space_before`, `space_after`. Built-ins: `heading1..3`, `small`, `header`, `footer` |
| `header` / `footer` | `left`, `center`, `right` (templated; `{page}` and `{pages}` are page tokens), `style`, `line` (rule), `lines` (height in lines) |
| `body` | List of blocks |

Fonts (`style.font`): `noto-sans` (default, Latin), `noto-sans-malayalam`,
`noto-sans-devanagari`. Malayalam/Devanagari text inside any style switches to
the right font automatically, so mixed-script text needs no extra config.

Blocks — every block accepts `"when": "<expression>"` and is skipped when false:

| Type | Keys |
| --- | --- |
| `paragraph` / `text` | `text`, `style`, `align` |
| `heading` | `text`, `level` (1–3), `style`, `align` |
| `table` | `columns` (`header`, `value`, `width` in pt or `"40%"`, `align`), `source` + `as` (one row per item), static `rows`, `style`, `header_style`, `show_header`, `repeat_header` (default true — repeats on every page), `border`, `padding`, `header_background` |
| `list` | `items` and/or `source` + `as` + `item`; `ordered`, `start`, `indent`, `style` |
| `image` | `source` (expression resolving to an `image` mapping target), `width`/`height`/`size`, `align` |
| `qr` | `source` (a `qr` mapping target) or `value` (template, encoded directly), `size`, `align`, `error_correction` |
| `group` | `blocks`, optional `source` + `as` to repeat blocks per item |
| `spacer` | `height` |
| `line` | `thickness`, `color`, `space_before`, `space_after` |
| `page_break` | — |

Text uses Jinja2 (sandboxed). Variables: `data` (request payload — the current
record in bulk), `request` (whole payload, bulk only), `meta` (`tenant_id`,
`key`, `entity_id`, `locale`, `correlation_id`, `user_id`, `job_id`), every
mapping target, and inside repeats the `as` name plus `loop.index`,
`loop.first`, `loop.last`. Filters: standard Jinja filters plus `format_date`,
`format_number`, `nl2br`. Inline markup `<b>`, `<i>`, `<u>`, `<br/>`,
`<font color="…">` is allowed in template text; values from request data are
HTML-escaped automatically. Referencing a missing value fails the job — use
`{{ x | default('') }}` for optional values.

### 7.2 `data_config` (mapping)

| Key | Description |
| --- | --- |
| `mappings` | Ordered list; each produces `target`, visible to later mappings and the layout |
| `localization` | `module` + inline `messages` per locale |
| `significant_fields` | JSONPaths identifying the document for reuse; omit to use the whole payload |
| `request_schema` | JSON Schema the payload must satisfy (checked at job creation → `400`) |
| `filename` | Template for the stored file name (`.pdf` appended) |
| `sync_render` | `false` forbids `POST /render/` |
| `bulk` | `records_path` (default `$.records`), `merge`, `merge_partial`, `max_records_per_document` (default `PDF_MAX_RECORDS_PER_DOCUMENT`), `bulk_only` |

Mapping types (all accept `target`, `required` (default true for most), `default`):

| Type | Keys | Example |
| --- | --- | --- |
| `direct` | `path` (JSONPath on `data`) or `value`; `many`; `columns`; `labels`; `transform` (`upper/lower/title/capitalize/strip`) | `{"type": "direct", "target": "names", "path": "$.accused[*].name", "many": true}` |
| `external_api` | `url`, `method` (`GET`/`POST`), `params`, `credentials`, `path`, `fields`, `many` | see §7.3 |
| `derived` | `expression`, or `function` (`sum`, `count`, `join`, `concat`, `coalesce`, `today`, `now`, `age`, `index`) with `args` (expressions) | `{"type": "derived", "target": "total", "function": "sum", "args": ["fees"]}` |
| `format` | `source`, `format` (`date`, `number`, or a case transform); date: `pattern`, `input_format` (`iso`, `epoch`, `epoch_ms`, strptime), `timezone` (default `Asia/Kolkata`); number: `decimals`, `grouping` (`international`, `indian`, `none`) | `{"type": "format", "target": "d", "source": "data.date", "format": "date", "pattern": "%d/%m/%Y"}` |
| `localization` | `code` or `source`; `module`, `locale`, `default` (`{code}` placeholder) | `{"type": "localization", "target": "title", "code": "SUMMONS_TITLE"}` |
| `image` | `source`, `source_type` (`url`, `base64`, `file` = `apps.files` id), `max_width`, `max_height`, `on_error` (`fail`/`placeholder`) | `{"type": "image", "target": "seal", "source": "data.seal_file_id", "source_type": "file"}` |
| `qr` | `template` or `source`; `error_correction` (`L/M/Q/H`), `box_size`, `border` | `{"type": "qr", "target": "qr", "template": "https://x/{{ case_number }}"}` |

### 7.3 `external_api` mapping

```json
{
  "type": "external_api",
  "target": "advocate",
  "method": "GET",
  "url": "https://hrms.internal/advocates/{{ data.advocate_id }}",
  "params": {"tenant": "{{ meta.tenant_id }}"},
  "credentials": "hrms",
  "path": "$.advocate",
  "fields": {"name": "$.name", "bar_no": "$.barRegistrationNumber"}
}
```

* `credentials` names an entry of `PDF_SERVICE_CREDENTIALS` (settings, not the
  DB), e.g. `PDF_SERVICE_CREDENTIALS = {"hrms": {"Authorization": "Bearer …"}}`.
  The caller's own authorization is never forwarded or stored.
* Headers `X-Tenant-Id`, `Accept-Language`, `X-Correlation-Id` are sent.
* Timeouts/5xx are retried `PDF_EXTERNAL_API_MAX_RETRIES` times in-call, then
  the job retries with backoff; 4xx fails the job.
* Set `PDF_FETCH_ALLOWED_HOSTS` to restrict which hosts may be called.
* For a quick test without a real service, point `url` at any reachable JSON
  endpoint (e.g. an internal mock) — templates with `external_api` cannot use
  `POST /render/`.

### 7.4 Localization service (optional)

If `PDF_LOCALIZATION_BASE_URL` is set, codes not found in the inline
`messages` are fetched with
`GET {base}?tenant_id=…&module=…&locale=…`, expecting either
`{"CODE": "message"}` or `{"messages": [{"code": "CODE", "message": "…"}]}`,
cached for `PDF_LOCALIZATION_CACHE_TIMEOUT_SECONDS`.

### 7.5 Settings

All read from the environment in `config/settings/base.py`; see `README.md`
and `.env.example` for the full list. The ones you are most likely to tune:

| Setting | Default | Notes |
| --- | --- | --- |
| `FILE_SYSTEM_USER_ID` | `""` | Attribution for jobs without a requesting user |
| `PDF_MAX_RECORDS_PER_DOCUMENT` | `100` | Bulk chunk size (per-template override in `bulk`) |
| `PDF_BULK_MAX_PARALLEL_CHUNKS` | `4` | Chunks in flight per job |
| `PDF_SYNC_RENDER_TIMEOUT_SECONDS` | `10` | `/render/` deadline |
| `PDF_JOB_MAX_RETRIES` / `PDF_RETRY_DELAY_BASE_SECONDS` / `PDF_RETRY_DELAY_MAX_SECONDS` | `3` / `30` / `900` | Job-level retry with exponential backoff |
| `PDF_CONFIG_CACHE_TIMEOUT_SECONDS` | `3600` | Template config cache (invalidated automatically on save) |
| `PDF_SIGNATURE_CONTAINER_BYTES` | `16384` | Signing container size |
| `PDF_SIGNATURE_HASH_ALGORITHM` | `SHA256` | Must equal `CDAC_ESIGN_HASH_ALGORITHM` |
| `PDF_MAX_SIGN_INPUT_BYTES` | `FILE_MAX_SIZE_BYTES` | Largest source PDF accepted for signing |

Retry policy: dependency (external API, localization, image download),
storage and database failures retry with backoff up to `PDF_JOB_MAX_RETRIES`;
invalid configuration or request data fail immediately; renderer errors retry
once.

---

## 8. Signing primitives (used by eSign)

`apps.pdf.services.signing` (pyHanko) — in-process only, no REST endpoint, no
job, no storage, no keys:

```python
from apps.pdf.services.signing import prepare_for_signing, embed_signature

prepared = prepare_for_signing(pdf_bytes, {
    "page": 1, "x": 380, "y": 60, "width": 160, "height": 60,
    "reason": "Approved", "location": "District Court, Ernakulam",
    "signer_name": "Presiding Officer",
})
# prepared.prepared_document -> bytes to store verbatim
# prepared.document_hash     -> lowercase hex digest to send to the ESP
# prepared.field_name        -> "Signature1" (next free name if already signed)

signed_pdf = embed_signature(prepared.prepared_document, pkcs7_der_bytes, prepared.field_name)
```

* `page` is 1-based; negative counts from the end (`-1` = last page).
  Coordinates are PDF points from the bottom-left and the box must fit the page.
  Unknown placeholder keys are rejected.
* The field gets a visible bordered appearance with
  "Digitally signed by …", "Reason: …", "Location: …"; Malayalam/Devanagari
  names are drawn with the bundled fonts.
* Preparation is an incremental update; existing signatures remain valid.
  `embed_signature` changes only the reserved container bytes.
* `embed_signature` accepts prepared documents up to
  `PDF_MAX_SIGN_INPUT_BYTES + 2 × PDF_SIGNATURE_CONTAINER_BYTES + 64 KiB`, matching
  the eSign adapter's read limit.
* Errors (`apps.pdf.exceptions`, all subclasses of `PDFSigningError`):
  `PDFNotParsable`, `PDFEncrypted`, `PDFTooLarge`, `PDFPageOutOfRange`,
  `PDFInvalidPlaceholder`, `PDFSignatureFieldMissing`,
  `PDFSignatureContainerTooSmall`, `PDFInvalidPKCS7`.

Integration gaps found against the current eSign branch are listed in
[pdf-esign-integration-issues.md](pdf-esign-integration-issues.md).

---

## 9. Error codes

| `code` | Where | Meaning | Retried |
| --- | --- | --- | --- |
| `PDF_TEMPLATE_NOT_FOUND` | API 404 / job | Unknown or inactive key / version | no |
| `PDF_INVALID_REQUEST_DATA` | API 400 / job | Payload doesn't fit the template (missing value, bad date, schema, bad image) | no |
| `PDF_INVALID_CONFIG` | job | Template config can't be applied, stored file rejected, or no user to attribute the upload to | no |
| `PDF_DEPENDENCY_UNAVAILABLE` | job / API 503 | External API, localization or image host failing | yes |
| `PDF_STORAGE_UNAVAILABLE` | job | `apps.files` upload failed | yes |
| `PDF_DATABASE_UNAVAILABLE` | job | Database connectivity | yes |
| `PDF_RENDER_FAILED` | job | Renderer error | once |
| `PDF_INTERNAL_ERROR` | job | Unexpected error (details only in worker logs) | no |
| `PDF_BULK_PARTIAL` | job | Some bulk records failed | — |
| `PDF_INVALID_TRANSITION` | API 409 | Cancel of a terminal job; partial delete failure | — |
| `PDF_JOB_ACTIVE` | API 409 | Delete of a running job | — |
| `PDF_NO_DOCUMENT` | API 404 | Nothing to download | — |
| `PDF_SYNC_RENDER_NOT_ALLOWED` | API 400 | Template not eligible for `/render/` | — |
| `PDF_SYNC_RENDER_TIMEOUT` | API 504 | `/render/` exceeded its deadline | — |

---

## 10. Troubleshooting

| Symptom | Check |
| --- | --- |
| Job stays `QUEUED` | Is the Dramatiq worker running and connected to the same Redis (`DRAMATIQ_BROKER_URL`)? Look for `event=PDF_JOB_PROCESSING` in worker logs. |
| `403` on POST | Missing `X-CSRFToken` header, or user's registration isn't `COMPLETE`. |
| `404 PDF_TEMPLATE_NOT_FOUND` | Template `is_active`, and exactly one version with *Is active* ticked. |
| Job `FAILED` / `PDF_INVALID_CONFIG` "FILE_SYSTEM_USER_ID …" | Job created without a user (in-process caller) and no system user configured — see §3.1. |
| Admin rejects a version | Read the message: it names the JSON path (`body/2/columns/0/value: …`). |
| Can't edit a version | It has been used by a job — create a new version. |
| Malayalam shows as boxes | `uharfbuzz` missing in the image; reinstall requirements. |
| Logs | Logger `apps.pdf`: `event=PDF_JOB_CREATED/QUEUED/PROCESSING/COMPLETED/FAILED`, `PDF_RETRY_SCHEDULED`, `PDF_RETRY_EXHAUSTED`, `PDF_BULK_PLANNED/FINALIZED`, `PDF_RENDERED`, `PDF_DEPENDENCY_CALL`, `PDF_SIGNING`, each with `job_id`, `key`, `tenant_id`, `status`, `correlation_id`. |
