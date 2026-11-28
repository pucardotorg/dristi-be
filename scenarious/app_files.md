# Files scenarios

Scenario IDs for the file storage service integration tests (spec 0014,
marked per spec 0037 §15). Each table row maps to a test tagged
`@pytest.mark.scenario("<ID>-<#>")` — row 2 of `FILE-UPLOAD` is
`FILE-UPLOAD-2`. IDs are assigned manually; once a test carries one it is
never renumbered or reused.

```bash
cd src
pytest --scenario FILE-UPLOAD-2                          # run one scenario
pytest apps/files --scenario-report scenario-map.json    # regenerate the ID → test map
```

`apps.files` exposes **no REST API** in this iteration (spec 0014): its real
surfaces are the service functions (`apps.files.services`,
`apps.files.documents`) and the Django admin, so flows walk those (spec 0037
§1 shapes 2–3). Per-endpoint-style coverage of every validation branch lives
in `apps/files/tests/test_services.py` and `test_documents.py`; the tables
below pin multi-step flows, all-or-nothing side effects, admin-driven
visibility, and the consumer contracts other apps rely on.

Every flow uses the `files_storage` fixture (`InMemoryStorage` on the `files`
alias) so storage side effects can be asserted, and uploads are attributed
to a real `User` (`user_id` is required). Nothing here wraps `upload_file`
in an outer transaction — storage writes are not transactional (spec 0014
§9).

## Upload — all-or-nothing, metadata and tags

ID: FILE-UPLOAD
Endpoints: `apps.files.services.upload_file` · `get_file` (spec 0014 §3, §6, §9)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a user | `upload_file` with two entries (a PDF, then an image) in one call | both ids returned in input order; `get_file` on each returns the recorded `file_name`, `content_type`, `file_size`, sorted `tags` — and never `storage_path`, `is_active` or the audit fields |
| 2 | a user | one entry tagged `["Identity", " identity ", "Address Proof"]` | exactly two `FileTag` rows exist (`identity`, `address-proof`) — names slugify and dedupe; `get_file` reports the sorted slugs |
| 3 | a user | a two-file call whose second entry has `file_type="PDF"` (member name, not the stored value) | `ValidationError` keyed `files[1].file_type`; **no** `File` rows and **no** objects in storage — validation runs before any write |
| 4 | a user | a two-file call where the second storage write fails (storage fake made to fail on the second `save`) | the first object is deleted again, no `File` rows exist, and the original exception propagates |
| 5 | a user | a call whose database insert fails after the storage writes | every written object is discarded and the exception propagates — a file never has a row without an object, best-effort never an object without a row |

Notes:

- Rows 4–5 inject failure at the settings boundary (a failing storage
  backend via `override_settings`, as `override_settings(STORAGES=...)`), not
  by patching the service (spec 0037 §3.1); cleanup errors during rollback
  are swallowed so they cannot mask the original error.
- Tests: `apps/files/tests/integration/test_upload_flow.py`.

## Read, search and delete — the metadata lifecycle

ID: FILE-LIFECYCLE
Endpoints: `get_file` · `get_file_content` · `search_file` · `delete_file` (spec 0014 §6–7)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | an uploaded PDF | `get_file_content(file_id)` | a readable stream returning the exact uploaded bytes; the caller closes it |
| 2 | an uploaded file | `get_file`, `get_file_content` and `delete_file` with a malformed id, then with a random UUID | each raises `FileNotFound` — unknown and malformed ids are indistinguishable, never `None` |
| 3 | an uploaded file whose recorded size exceeds `FILE_MAX_READ_BYTES` (`override_settings`) | `get_file_content(file_id)` | `ValidationError` raised **before** the object is opened — the storage fake records no `open` call |
| 4 | an uploaded tagged file | `delete_file(file_id)`, then `delete_file(file_id)` again | the object and the `File` row are gone; the tag links go but the `FileTag` rows survive; the second call raises `FileNotFound` — deletion is not silently idempotent |
| 5 | files for two users, two orgs, mixed types and tags | `search_file` per filter, then combined (`organization_id` + `file_type` + `tags`) | each filter narrows as ANDed; `tags` requires **all**; unknown filter keys are ignored; `file_type="PDF"` (wrong case) returns an empty page, not an error |
| 6 | 25 uploaded files | `search_file(page=2, page_size=20)`, then `page=9` | page 2 holds the oldest 5 (newest-first, `-created_at`); a page past the end serves the last page and reports it; `page=0` / `page_size=0` are `ValidationError`, never silently re-paged |

Tests: `apps/files/tests/integration/test_lifecycle_flow.py`.

## Admin — visibility and the add ban

ID: FILE-ADMIN
Endpoints: `/admin/files/file/` · `/admin/files/filetag/` (spec 0014 §6.4, §11; spec 0037 §5)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | an uploaded file | a superuser unchecks `is_active` via the change-view POST | `get_file` and `get_file_content` raise `FileNotFound` and `search_file` no longer lists it — every read path hides deactivated files |
| 2 | the deactivated file | the superuser re-checks `is_active` | the file reappears on every read path — deactivation is a soft hide, not a delete |
| 3 | the deactivated file | `delete_file(file_id)` | the delete succeeds — cleanup is the one operation that must reach deactivated files |
| 4 | — | the superuser opens the admin add form for `File` | adding is refused (`has_add_permission` is `False`): a row created there would point at a storage key with no object behind it |
| 5 | — | the superuser adds the tag `Address Proof` through `FileTagAdmin` | it is stored as `address-proof`; a later upload tagged `"Address Proof"` reuses that row |

Notes:

- Every admin beat POSTs the real admin form with a `force_login` superuser
  (spec 0037 §5), then the service is re-queried — the sequence *operator
  edits in admin → service behavior changes* is the contract.
- Tests: `apps/files/tests/integration/test_file_admin_flow.py`.

## User documents — the format gate consumers share

ID: FILE-DOCUMENTS
Endpoints: `apps.files.documents.document_error` · `store_documents` · `discard_documents` (spec 0014 §3.1)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | uploads declared `application/pdf`, `image/jpeg`, `image/png` with matching extensions and leading bytes | `document_error` on each | `None` for all three — and each upload is left rewound for the real storage pass |
| 2 | a file named `scan.pdf` declared `application/pdf` whose bytes are a PNG | `document_error` | refused — the declared type and the name are client hints; the leading bytes decide |
| 3 | a real PDF upload over `FILE_MAX_SIZE_BYTES` (`override_settings` to a tiny limit) | `document_error` | refused on size; `store_documents` with the same upload raises `ValidationError` and stores nothing |
| 4 | three checked uploads | `store_documents` then `discard_documents` on the returned ids | all three are stored in one all-or-nothing `upload_file` call with the caller's tags, then all three are deleted; a second `discard_documents` only logs — cleanup failures never raise |

Notes:

- This is the seam `dristi_requests` and `users` registration call before
  their own 400s; the table pins the shared contract once so consumers can
  rely on it (spec 0014 §8.1).
- Tests: `apps/files/tests/integration/test_documents_flow.py`.

## Consumers — the referencing contract

ID: FILE-CONSUMERS
Endpoints: `apps.files.services.delete_file` against files a consumer references (spec 0014 §5, §6.2)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a request submitted through `POST /api/v1/dristi-requests/` with one document | `delete_file(document.file_id)` | `django.db.models.ProtectedError` — `RequestDocument.file` is `PROTECT`, so the row survives; the stored object is already gone (spec 0014 §6.2 known gap, open question 9), which is why consumers must never delete a file something else may reference |
| 2 | the same request | a superuser cancels nothing and the requester reads the trail | cancelling, rejecting or resubmitting never deletes documents: the `File` rows and `RequestDocument` links of every round remain readable (spec 0010 §7.2) |

Notes:

- Row 1 is pinned as documentation of the current guard + gap, not as
  desired end state; when open question 9 is fixed the scenario is updated
  in place (the ID is never reused).
- The reverse flow — a failed submission discarding its uploads — is owned
  by `apps.dristi_requests` (`REQ-SUBMIT-6`), not duplicated here.
- Tests: `apps/files/tests/integration/test_consumers_flow.py`.
