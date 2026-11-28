# Dristi requests scenarios

Scenario IDs for the request-and-approval workflow integration tests (spec
0010, marked per spec 0037 §15). Each table row maps to a test tagged
`@pytest.mark.scenario("<ID>-<#>")` — row 2 of `REQ-SUBMIT` is
`REQ-SUBMIT-2`. IDs are assigned manually; once a test carries one it is
never renumbered or reused.

```bash
cd src
pytest --scenario REQ-SUBMIT-2                                  # run one scenario
pytest apps/dristi_requests --scenario-report scenario-map.json # regenerate the ID → test map
```

Per-endpoint success/shape/error coverage lives in
`apps/dristi_requests/tests/test_views.py` (spec 0000 §13). The tables below
pin only cross-call flows (spec 0037 §1): seeded configuration and types,
multi-actor submission→decision sequences, document storage side effects,
and admin changes between calls.

Every flow needs the `tenant.state_code` configuration row (the autouse
fixture creates `KL`) and the `files_storage` fixture pointing the `files`
alias at `InMemoryStorage`; actors use one `APIClient` per user (spec 0037
§4.1). "Seeded type" below means `manage.py seed
data/seed/core/dristi_requests/` (`LAWYER_BAR_UPDATE`,
`ADVOCATE_REGISTRATION`, `CLERK_REGISTRATION`, each with one
`BAR_ID_APPROVER` step); other types are built per test with the
`simple_type` / `two_step_type` style factories.

## Request types — seeded configuration read back

ID: REQ-TYPES
Endpoints: `GET /api/v1/dristi-requests/request-types/` · `GET /api/v1/dristi-requests/request-types/{request_type_id}/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `data/seed/core/dristi_requests/` seeded once per module + a `BAR_ID_APPROVER` group | list request types as any authenticated user | 200, exactly the three seeded codes, each with `name`, `min_documents` and `schema` verbatim from the TOML |
| 2 | the seeded types | retrieve `LAWYER_BAR_UPDATE` by id | 200, `min_documents` = 1, schema requires `name` and `bar_number` |
| 3 | the seeded types, then one type deactivated via the admin change view | re-list | the deactivated type is gone from the list (`RequestType.objects.active()`), and creating a request of that code is a 400 on `request_type` |

Notes:

- Seed once per module; the fixture must depend on `django_db_setup` (spec
  0037 §7). The seeded codes are production codes, so tests must not create
  colliding `RequestType` rows — seeding is insert-only.
- Tests: `apps/dristi_requests/tests/integration/test_request_types_api.py`.

## Submit — create with documents, numbering and routing

ID: REQ-SUBMIT
Endpoints: `POST /api/v1/dristi-requests/` (multipart; spec 0010 §7, §9.1)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a type with `min_documents=1` and one step routed to a group with one member | the requester POSTs valid `attributes` JSON + one PDF | 201, status `pending`, `request_number` = `KL-REQ-00001`, documents carry `file_id`s in upload order, and one pending approval exists for the group member |
| 2 | the same setup | the requester submits two requests in a row | numbers are sequential (`KL-REQ-00001`, `KL-REQ-00002`) from the counter row — never `count()+1` (spec 0010 §1.1) |
| 3 | the same setup | `attributes` missing a schema-required key | 400 with code `E02006` on `attributes`; no `Request`, no `File` rows, storage empty |
| 4 | the same setup | no `documents` part | 400 with code `E02007` on `documents` (minimum count); nothing stored |
| 5 | the same setup | a document whose bytes do not start with `%PDF-` | 400 with code `E02007` on `documents` naming the file — the declared content type is a hint, the leading bytes decide (spec 0014 §3.1) |
| 6 | the step's group has no members | the requester POSTs a valid submission | 409 with code `E02003`; the uploaded documents are discarded — no `File` rows, no stored objects (spec 0010 §7.2) |
| 7 | the `tenant.state_code` row is deleted | the requester POSTs a valid submission | 503 with code `E02008`; documents discarded, no request |
| 8 | the `tenant.state_code` row holds `kl` (lowercase) | a valid submission | 201, number prefixed `KL-REQ-` — the value is trimmed and upper-cased before use |

Notes:

- Rows 3–7 assert the absence of side effects with the ORM and the
  `files_storage` handle: the create path must leave nothing behind on
  failure (spec 0010 §7.2).
- Row 7 uses the ORM to delete the configuration row (no admin surface for
  the failure itself); row 8's edit can go through the admin change view.
- Tests: `apps/dristi_requests/tests/integration/test_submit.py`.

## Decide — multi-step routing, conditions and the hook

ID: REQ-APPROVE
Endpoints: `GET /api/v1/dristi-requests/approvals/` · `GET /api/v1/dristi-requests/approvals/{approval_id}/` · `POST /api/v1/dristi-requests/approvals/{approval_id}/decide/` (spec 0010 §4, §8, §9.2)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a two-step type (step 0 → `LEVEL_ONE`, step 1 → `LEVEL_TWO`) and a submitted request | approver 1 lists their approvals | 200, exactly the step-0 approval, nested request shows data + documents; approver 2's list is empty |
| 2 | the same request | approver 1 decides `approved` with comments, then approver 2 decides `approved` | after step 0 the request stays `pending` with `current_step` = 1 and a new pending approval for approver 2; after step 1 the request is `approved`; the trail (`GET {id}/approvals/`) shows both rows with comments and `decided_at` |
| 3 | a two-step type whose step 1 has `condition = {"field": "data.amount", "op": "gt", "value": 1000}`, and a request with `amount` = 500 | approver 1 approves step 0 | step 1 is recorded `skipped` ("Step condition not met.") and the request is `approved` — conditions are evaluated lazily against the request's own data (spec 0010 §3) |
| 4 | the submitted two-step request | approver 2 POSTs decide on the step-0 approval | 404 — the approvals queue is scoped to the assignee, so another user's approval is simply not there; `E02004` remains the service-layer backstop in `services.decide` |
| 5 | the submitted two-step request | the requester (not in any approver group) POSTs decide | 404 — the requester is never eligible to approve their own request |
| 6 | the submitted two-step request | approver 1 approves step 0, then re-lists their queue with and without `?status=approved` | the default (pending) queue is empty, and the decided approval shows in the history filter with its comments and `decided_at` — step 1's approval only exists once step 0 is decided (lazy routing) |
| 7 | the submitted two-step request | approver 1 decides `rejected` with no `comments` | 400 with code `E00002` on `comments` — a reason is required to reject |
| 8 | the step-0 approval already decided | the same approver POSTs decide again | 400 with code `E02002` — a decided approval cannot be decided again |
| 9 | a submitted request whose type has a test-registered approval hook | the final step is approved | the hook runs inside the deciding transaction; when the hook raises, the whole decision rolls back — the approval stays `pending` and the request is not `approved` |

Notes:

- One client per actor (requester, approver 1, approver 2) — never one
  client re-authenticated mid-test (spec 0037 §4.1).
- Row 9 registers a hook with `register_hook` on a test-only type code; the
  profile side effects of the seeded registration types are owned and pinned
  by `apps.users` (spec 0037 §2 rule 1).
- Tests: `apps/dristi_requests/tests/integration/test_approve.py`.

## Lifecycle — reject, resubmit, cancel

ID: REQ-LIFECYCLE
Endpoints: `POST /api/v1/dristi-requests/{request_id}/resubmit/` · `POST /api/v1/dristi-requests/{request_id}/cancel/` · `GET /api/v1/dristi-requests/{request_id}/` · `GET /api/v1/dristi-requests/{request_id}/approvals/` (spec 0010 §2, §9.3)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a request rejected at step 0 with comments | the requester POSTs resubmit | 200, `version` = 2, status `pending`, `current_step` = 0, the **same** `request_number`; a new pending approval exists for the new round and the rejected one stays on the trail |
| 2 | the rejected request | the requester resubmits with corrected `data` and replacement `file_ids` | the new round carries the corrected data; the old `RequestDocument` links are replaced while the old `File` rows survive — documents are part of the audit trail (spec 0010 §7.2) |
| 3 | a pending request | the requester POSTs resubmit | 400 with code `E02001` — only rejected requests can be resubmitted |
| 4 | a pending request with a pending approval | the requester POSTs cancel | 200, status `cancelled`; the pending approval becomes `skipped` ("Request cancelled by the requester.") and leaves the approver's pending list; documents are kept |
| 5 | an approved request | the requester POSTs cancel | 400 with code `E02001` |
| 6 | a cancelled request | the former approver POSTs decide on its skipped approval | 400 with code `E02002` — the skipped approval is not pending and cannot be decided |
| 7 | another user's request | the outsider POSTs resubmit or cancel | 404 — the action routes are restricted to the requester (staff excepted) |

Notes:

- Row 2 drives `services.resubmit` directly: the API's resubmit action takes
  no body, so the corrected-data / replacement-documents path is only
  reachable at the service layer (spec 0037 §1 shape 2).

Tests: `apps/dristi_requests/tests/integration/test_lifecycle.py`.

## Documents — download authorization

ID: REQ-DOCS
Endpoints: `GET /api/v1/dristi-requests/{request_id}/documents/{document_id}/` (spec 0010 §9.4)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a submitted request with two PDF documents | the requester downloads the first document | 200, `Content-Disposition` attachment with the recorded `file_name`, recorded `content_type`, bytes identical to the upload |
| 2 | the same request | an approver on the trail downloads it | 200 — any approver on the trail is authorized |
| 3 | the same request | an outsider downloads it (and a bare `file_id` guess against the same URL pattern) | 404 — access is decided by the request's rules before `apps.files` is asked; a document is never served by `file_id` alone |
| 4 | the same request | a staff user (neither requester nor approver) downloads it | 200 |
| 5 | the same request, its document's `File` deactivated in the files admin | the requester downloads it | 404 — a deactivated file reads as not found (spec 0014 §6.4) |
| 6 | a document whose recorded size exceeds `FILE_MAX_READ_BYTES` (`override_settings`) | the requester downloads it | 413 with code `E02005` — the limit is checked from metadata before the object is opened |

Notes:

- Rows 5–6 swap fakes at the settings boundary (admin action /
  `override_settings`), never `mock.patch` of the service (spec 0037 §3.1).
- Tests: `apps/dristi_requests/tests/integration/test_documents_download.py`.

## Request numbers — configuration-driven series

ID: REQ-NUMBER
Endpoints: `GET /api/v1/dristi-requests/?request_number=...` · `GET /api/v1/dristi-requests/approvals/?request_number=...` (spec 0010 §1.1)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | `tenant.state_code` = `KL` seeded from `data/seed/core/configurations.toml` | the first request is created | 201 with `request_number` = `KL-REQ-00001`; the row is also searchable in `RequestAdmin` |
| 2 | a request rejected and resubmitted | re-read it | the number is unchanged across versions — only `version` moves |
| 3 | two requests numbered `KL-REQ-00001/2` | a superuser edits `tenant.state_code` to `BR` in the configuration admin, then a third request is created | 201 with `BR-REQ-00001` — a changed code starts a new series under the new prefix; the existing `KL-REQ-*` numbers are untouched |
| 4 | the requests from row 3 | `GET /dristi-requests/?request_number=kl-req-00001` as the requester | 200 with exactly that request — the filter is exact and case-insensitive, still scoped to the caller's own requests |
| 5 | the requests from row 3 | the approver filters `/approvals/?request_number=KL-REQ-00002` | 200 with that request's approval, scoped to the approver's own queue |

Notes:

- Row 1's seed proves the production TOML parses and resolves (spec 0037
  §3); the other rows use the autouse `KL` fixture.
- Row 3 is the admin-between-calls shape: the edit goes through the real
  admin change view, then the API behavior changes.
- Tests: `apps/dristi_requests/tests/integration/test_numbering_flow.py`.
