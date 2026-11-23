# 0037 — DSC Token Signing with pyHanko (`apps.esign` + `addon.dsc_esign`)

## Status

Proposed

## References

- [0000 — API Coding Specification](0000-api-coding-spec.md) — envelope, error-code, and layering rules
- [0014 — File Storage Service](0014-file-storage-service.md) — `apps.files`, owns document persistence and the `file_id` reference
- [0015 — eSign Module and CDAC eSign Addon](0015-cdac-esign.md) — `apps.esign` domain, provider interface, transaction lifecycle this spec extends
- [0016 — PDF Service](0016-pdf-services.md) — `apps.pdf`, owns signature-container preparation and PKCS#7 embedding
- `PRDs/signing-methods.md` — owner decisions: `SGM-02` (DSC), `SGM-05` (per-state `signingMethods`)
- POC: `dristi-solutions/pyhanko-bulksign` — proven local pyHanko DSC agent (Capricorn replacement), real-token verified

> **Scope note.** The domain (transaction lifecycle, state machine, prepare/embed
> orchestration, audit) already lives in `apps.esign` ([0015](0015-cdac-esign.md)).
> This spec adds **DSC token signing** as a second digital-signing method behind
> the **same provider interface**, plus one new authenticated completion endpoint.
> Everything DSC-specific (local-agent contract, detached-CMS assembly from the
> token) lives in `addon.dsc_esign`. PDF manipulation ([`apps.pdf`](0016-pdf-services.md))
> and file persistence ([`apps.files`](0014-file-storage-service.md)) are reused
> in-process through their published service functions; this spec neither
> implements nor re-specifies them.

## Context

`PRDs/signing-methods.md` separates **digital signing** (the umbrella: mobile OTP,
DSC, Aadhaar e-sign) from **e-sign** (Aadhaar only). `SGM-02` is **DSC**: the
signatory signs with their **own Digital Signature Certificate** — a physical USB
token and PIN — and the signature is placed on **every document** in a session
(any number of documents). DSC is a *sibling* of the C-DAC Aadhaar e-sign of
[0015](0015-cdac-esign.md), switched on per state via `signingMethods` (`SGM-05`).

A working POC (`pyhanko-bulksign`) already signs court PDFs with a DSC token via
pyHanko and PKCS#11, replacing the proprietary Capricorn `pkiNetworkSign` agent.
It has been verified against a real HYP2003 token and supports ePass2003 /
WatchData ProxKey / SafeNet tokens.

Consequences that shape the design:

- **The DSC token is physical USB hardware on the signer's machine.** The server
  can never reach it, so — unlike C-DAC — the backend **cannot perform the
  signature**. Signing happens in a **local agent** on the signer's PC
  (`localhost`, the POC's `:1620`), exactly as Capricorn did.
- The backend **already** splits signing into the two primitives DSC needs:
  [`apps.pdf`](0016-pdf-services.md) `prepare_for_signing` computes a **ByteRange
  digest** over a PDF with an empty signature container, and `embed_signature`
  fills that container with a **detached PKCS#7**. A DSC token can sign that
  digest and return exactly such a PKCS#7. pyHanko is already a backend
  dependency.
- There is **no third party and no cross-site redirect**: the signature comes
  from the signer's own browser/agent inside their authenticated session. So,
  unlike the anonymous C-DAC callback ([0015](0015-cdac-esign.md) #6.3), DSC
  completion can and should be an **authenticated JSON** call.
- Signing is **synchronous and local** from the backend's view: `prepare`,
  `embed`, and `store` are fast in-process operations; token latency is on the
  client. No ESP wait, no queue.

## Goals

- Add DSC as a second digital-signing method **reusing** the `apps.esign`
  transaction lifecycle, state machine, prepare/embed orchestration, file
  storage, permissions, retry, and audit — introducing the minimum new surface.
- Implement DSC as an `ESignProvider` selected by configuration, so C-DAC and DSC
  coexist and the method offered is driven by per-state `signingMethods`.
- Return to the client the **digest to be signed** and the **local-agent
  descriptor** from the existing initiation endpoint, carried in the existing
  provider-agnostic response fields.
- Add one **authenticated JSON completion endpoint** that accepts the token's
  detached PKCS#7, embeds it via the PDF Service, stores the signed PDF, and
  marks the transaction `SUCCESS` — reusing the C-DAC completion logic.
- Keep every DSC wire detail (local-agent contract, CMS assembly) inside
  `addon.dsc_esign`.
- Keep all token and key material on the signer's machine; the backend handles
  only the public digest and the resulting detached signature.

## Non-goals

- Implementing or re-specifying PDF ByteRange computation, container
  reservation, or PKCS#7 embedding (PDF Service module, [0016](0016-pdf-services.md) #14).
- Implementing document storage (File Storage module, [0014](0014-file-storage-service.md)).
- The **local agent itself** (`pyhanko-bulksign`): its packaging, driver
  bundling, token discovery, PIN handling, and PKCS#11 session management are
  owned by that project. This spec defines only the HTTP contract the agent must
  satisfy (#7) and the single behavioural change it requires (#7.2).
- Batch signing / batch certificates (`SGM-04`) — a distinct method with its own
  flow; out of scope here (see [0015](0015-cdac-esign.md) and the PRD).
- India CCA trust-chain validation, RFC-3161 TSA timestamps, PAdES-LTV, and
  verification of previously signed PDFs — recommended follow-ups (#17, #18).
- Server-side HSM/soft-certificate signing.
- Any new broker. The DSC main flow is synchronous; only the existing 0015
  maintenance tasks remain async.

---

## 1. Module placement and dependency direction

```text
src/
├── apps/
│   ├── esign/                     # 0015 — domain, models, APIs; THIS SPEC adds
│   │   │                          #        a completion service + endpoint
│   │   ├── providers/base.py      # reused provider ABC
│   │   └── services/completion.py # NEW — DSC JSON completion (factored from callback.py)
│   ├── pdf/                       # 0016 — PDF Service (prepare/embed), reused as-is
│   └── files/                     # 0014 — File Storage Service, reused as-is
├── addon/
│   ├── cdac_esign/                # 0015
│   └── dsc_esign/                 # THIS SPEC — DSC provider + local-agent contract
└── config/settings/base.py        # the only wiring point
```

```text
addon.dsc_esign   -- imports -->  apps.esign (provider base class, dataclasses, exceptions)
apps.esign        -- never imports --> addon.*
apps.esign        -- imports -->  apps.pdf / apps.files *service functions only*
config.settings   -- references --> "addon.dsc_esign.provider.DSCESignProvider"
```

The backend gains **no PKCS#11 dependency**: `python-pkcs11` and the vendor
modules live only in the local agent.

### 1.1 Layout

```text
src/addon/dsc_esign/
├── __init__.py
├── apps.py
├── provider.py          # DSCESignProvider(ESignProvider)
├── constants.py         # provider name, form-field keys, agent form keys
├── config.py            # resolve_config(): DSC_AGENT_URL, hash alg, container checks
├── agent_contract.py    # shapes of the /sign request + response (documentation + helpers)
└── tests/
    ├── test_provider.py
    └── test_config.py
```

---

## 2. End-to-end flow

```text
Signer's browser            apps.esign (backend)                 Local DSC agent (:1620)        apps.pdf / apps.files
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 POST /esign/_esign  ───────▶ initiate_esign (0015 #2)
                              check_can_sign; reject_if_in_progress
                              files.get_content(file_id) ──────────────────────────────────────▶ fetch source PDF
                              pdf.prepare_for_signing → (prepared, document_hash, field_name)
                              store_placeholder → placeholder_file_id
                              create ESignTransaction(PENDING, document_hash)
                              DSCESignProvider.build_initiation
                                 → esign_url = DSC_AGENT_URL, form_fields{digest, field_name, …}
     ◀── 201 {transaction_id, esign_url, form_fields{digest,…}}
 POST {agent}/sign (digest, field_name) ──────────────────────▶ PKCS#11: token signs digest (PIN given at agent START)
                                                                → detached CMS (PKCS#7)
     ◀───────────── {status:"ok", pkcs7}
 POST /esign/transactions/{id}/_complete {pkcs7} ─▶ gate: lock, PENDING→SIGNING (0015 #8.2)
                              decode + validate pkcs7
                              pdf.embed_signature(placeholder, pkcs7, field_name) → signed PDF
                              files.upload(signed) → signed_file_id ─────────────────────────────▶ store signed PDF
                              mark_success(signed_file_id)
     ◀── 200 {status:"SUCCESS", signed_file_id}
 (bulk: repeat per document; PIN entered once at agent START)
 GET /esign/transactions/{id} ──▶ status (idempotent source of truth)
```

The only steps that differ from [0015](0015-cdac-esign.md) are the **provider**
(`build_initiation` targets the local agent and carries the digest) and the
**completion channel** (authenticated JSON instead of the anonymous ESP
callback). Preparation, embedding, storage, state machine, dedup, retry, and the
status endpoint are unchanged.

---

## 3. Provider interface (`apps.esign.providers.base`)

DSC implements the existing ABC from [0015](0015-cdac-esign.md) #3 with no change
to the contract:

- **`build_initiation(transaction, document_hash) -> ESignInitiation`** — returns
  `esign_url = DSC_AGENT_URL`, `form_fields` carrying the digest and field
  metadata, and `provider_transaction_id = "dsc-" + str(transaction.pk)`. It does
  **no** network call, no DB, no PDF work (the digest is already computed).
- **`parse_response(payload)` / `verify_response(payload)`** — **not used by the
  DSC completion path.** DSC completion goes through the new authenticated service
  (#8), not the anonymous callback that invokes `parse_response`/`verify_response`.
  The provider implements them to satisfy the ABC; `verify_response` is a no-op
  because trust comes from the authenticated session and the digest binding, not
  from a response signature. (This is the one place DSC legitimately diverges
  from the C-DAC provider usage; see #16.)

`form_fields` is opaque to the UI, exactly as in [0015](0015-cdac-esign.md) #6.1:
the browser posts it verbatim to `esign_url` (here, the local agent).

---

## 4. PDF Service and File Storage contracts consumed

Reused **unchanged** from [0015](0015-cdac-esign.md) #4.

### 4.1 PDF Service (`apps.pdf`, [0016](0016-pdf-services.md) #14)

- `prepare_for_signing(document, placeholder) -> PreparedDocument(prepared_document, document_hash, field_name)`
  — reserves an empty `/Contents` container of `PDF_SIGNATURE_CONTAINER_BYTES`,
  renders the visible appearance from `placeholder`, and returns the ByteRange
  digest. **The `document_hash` is the digest the token signs.**
- `embed_signature(prepared_document, pkcs7, field_name) -> bytes` — writes the
  detached PKCS#7 into the reserved container, changing no other byte.

The DSC CMS must use `ADOBE_PKCS7_DETACHED` and the digest algorithm named by
`PDF_SIGNATURE_HASH_ALGORITHM`, and must fit `PDF_SIGNATURE_CONTAINER_BYTES`.

### 4.2 File Storage Service (`apps.files`, [0014](0014-file-storage-service.md) #2)

- `upload(...)` for the placeholder (at initiation) and the signed PDF (at
  completion), tagged `esign`, module, entity ([0015](0015-cdac-esign.md) #4.2).
- `get_metadata` / `get_content` for the source and placeholder documents.

---

## 5. `ESignTransaction` model

Reused **as-is** from [0015](0015-cdac-esign.md) #5. No schema change:

- `provider` stores the DSC provider name; `(provider, provider_transaction_id)`
  stays unique, giving per-transaction dedup.
- `document_hash` and `signature_field_name` already exist and hold the digest
  and reserved field; completion needs nothing more.
- `sign_placeholder`, `placeholder_file_id`, `signed_file_id`, `request_audit`,
  `response_audit`, `attempt_count`, `retry_of`, timestamps — all reused.

### 5.1 State machine

Unchanged from [0015](0015-cdac-esign.md) #5.1: `PENDING → SIGNING →
SUCCESS | FAILURE`, plus `PENDING → EXPIRED`. The DSC completion service drives
`PENDING → SIGNING → SUCCESS/FAILURE` through the existing
`mark_signing` / `mark_success` / `mark_failed` transitions.

### 5.2 Constraints and indexes

Unchanged ([0015](0015-cdac-esign.md) #5.2). The success-requires-signed-file and
signing-requires-placeholder check constraints apply identically.

---

## 6. APIs

Two endpoints are **reused** (`_esign`, status, retry — [0015](0015-cdac-esign.md)
#6) and one is **new** (`_complete`). All follow [0000](0000-api-coding-spec.md):
DRF serializers, the `meta` envelope, `error_responses()`, Swagger tags from the
owning app (`esign`).

### 6.1 `POST /api/v1/esign/_esign` — initiate (reused, extended)

Unchanged request serializer (`ESignInitiateSerializer`); the active provider is
selected by configuration (#11). When the provider is DSC, the response fields
carry DSC values:

| Field | DSC meaning |
| --- | --- |
| `transaction_id` | `ESignTransaction` id. |
| `provider_transaction_id` | `dsc-<transaction_id>`. |
| `expires_at` | `PENDING` TTL (`ESIGN_TRANSACTION_TTL`). |
| `esign_url` | the local agent sign URL (`DSC_AGENT_URL`, e.g. `http://localhost:1620/sign`). |
| `form_method` | `POST`. |
| `form_fields` | `{digest, hash_algorithm, field_name, transaction_id, page, cood, size}` — posted verbatim to the agent. |

**Request**

```json
{
  "module": "orders",
  "file_id": "a1b2c3d4",
  "entity_type": "ORDER",
  "entity_id": "ORD-2026-000123",
  "sign_placeholder": {
    "page": 1, "x": 380, "y": 60, "width": 150, "height": 45,
    "signer_name": "Hon'ble Judge X"
  }
}
```

**Response `201`** (inside the standard envelope)

```json
{
  "transaction_id": "7c9e2b10-0000-4000-8000-000000000001",
  "provider_transaction_id": "dsc-7c9e2b10-0000-4000-8000-000000000001",
  "expires_at": "2026-11-23T15:45:00+05:30",
  "esign_url": "http://localhost:1620/sign",
  "form_method": "POST",
  "form_fields": {
    "digest": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "hash_algorithm": "sha256",
    "field_name": "Signature1",
    "transaction_id": "7c9e2b10-0000-4000-8000-000000000001",
    "page": "1", "cood": "380,60", "size": "150,45"
  }
}
```

Errors as [0015](0015-cdac-esign.md) #6.1: `ESIGN_NOT_A_PDF`,
`ESIGN_INVALID_PLACEHOLDER`, `ESIGN_NOT_PERMITTED`, `ESIGN_SOURCE_NOT_FOUND`,
`ESIGN_ALREADY_IN_PROGRESS`, `ESIGN_PDF_PREPARATION_FAILED`,
`ESIGN_FILE_STORAGE_UNAVAILABLE`, `ESIGN_REQUEST_BUILD_FAILED`,
`ESIGN_DISABLED`, `ESIGN_PROVIDER_NOT_CONFIGURED`.

### 6.2 `GET /api/v1/esign/transactions/{id}` — status (reused)

Unchanged ([0015](0015-cdac-esign.md) #6.2). The UI polls this for the outcome
and reads `signed_file_id` on `SUCCESS`.

### 6.3 `POST /api/v1/esign/transactions/{id}/_complete` — embed DSC signature (new)

Accepts the token's detached PKCS#7, embeds it, stores the signed PDF, and marks
the transaction `SUCCESS`. The authenticated, JSON analogue of the anonymous
C-DAC callback ([0015](0015-cdac-esign.md) #6.3).

- **Auth:** `IsAuthenticated` + `IsAuthenticatedAndRegistered`. The transaction
  must belong to the caller (`signer == request.user`), else `404`.
- **Provider guard:** the transaction's provider must be the DSC provider, else
  `409 ESIGN_TRANSACTION_NOT_PROCESSABLE`.
- **Idempotency:** the same `select_for_update` + status gate as
  [0015](0015-cdac-esign.md) #8.2 — a duplicate call on a `SUCCESS` row returns
  the existing result; a `SIGNING` row held elsewhere returns `409`.

**Request serializer** (`DSCCompleteSerializer`)

| Field | Type | Req | Description |
| --- | --- | --- | --- |
| `pkcs7` | string (base64) | yes | Detached CMS `SignedData` over `transaction.document_hash` for `signature_field_name`. |
| `certificate_subject` | string(≤256) | no | Token certificate CN; audit only (the cert blob is never stored). |
| `signed_at` | datetime (ISO-8601) | no | Token clock; audit only. |

**Request**

```json
{ "pkcs7": "MIIKxAYJKoZIhvcNAQcCoIIKt...", "certificate_subject": "CN=Judge X, O=eCourts, C=IN" }
```

**Response `200`** — the `ESignTransactionSerializer` body, so the client gets the
signed file id directly:

```json
{
  "transaction_id": "7c9e2b10-0000-4000-8000-000000000001",
  "status": "SUCCESS",
  "provider": "dsc",
  "source_file_id": "a1b2c3d4",
  "signed_file_id": "f9signed01",
  "completed_at": "2026-11-23T15:35:12+05:30"
}
```

Errors (#10): `400 ESIGN_SIGNATURE_MISSING | ESIGN_SIGNATURE_INVALID`,
`400 ESIGN_RESPONSE_STALE`, `403` (not the caller's transaction),
`404 ESIGN_TRANSACTION_NOT_FOUND`,
`409 ESIGN_TRANSACTION_NOT_PROCESSABLE | ESIGN_ALREADY_IN_PROGRESS`,
`502 ESIGN_PDF_EMBED_FAILED | ESIGN_SIGNED_UPLOAD_FAILED`.

### 6.4 `POST /api/v1/esign/transactions/{id}/_retry` — retry (reused)

Unchanged ([0015](0015-cdac-esign.md) #6.4). Re-preparation rebuilds the digest
and returns a fresh `form_fields` for a new token attempt.

---

## 7. Local-agent contract (`addon.dsc_esign` + `pyhanko-bulksign`)

The agent runs on the signer's machine and is reached by the browser at
`DSC_AGENT_URL`. The backend never calls it; it only tells the browser where it
is and what digest to sign.

### 7.1 `POST {DSC_AGENT_URL}` — sign a digest

**Request** — `application/x-www-form-urlencoded` or JSON, the `form_fields` from
#6.1:

| Field | Description |
| --- | --- |
| `digest` | hex ByteRange digest to sign. |
| `hash_algorithm` | `sha256` \| `sha384` \| `sha512` (matches `PDF_SIGNATURE_HASH_ALGORITHM`). |
| `field_name` | reserved signature field (for the agent's logs; the backend re-derives it). |
| `transaction_id` | correlation for the agent's logs. |

**Response** — JSON:

```json
{ "status": "ok", "pkcs7": "BASE64_DETACHED_CMS", "certificate_subject": "CN=Judge X,…", "error": "" }
```

On failure: `{ "status": "failed", "pkcs7": "", "error": "wrong PIN / token removed / …" }`.

Certificate and token errors (wrong PIN, token removed, no/multiple identities)
are surfaced here and shown by the browser; the browser then does **not** call
`_complete`, leaving the transaction `PENDING` (it later `EXPIRED`s, or the user
retries). `GET {agent}/health` (POC) may be probed before `_esign`.

### 7.2 Required change to the POC agent

The POC today signs the **whole PDF** and returns a **complete signed PDF**
(`pyhanko_signer.sign_pdf_bytes`, Capricorn-compatible `POST /`). For this
integration the agent must instead **sign the supplied digest** and return a
**detached CMS**:

- Replace `PdfSigner.sign_pdf` with pyHanko interrupted/raw signing:
  `signer.async_sign_raw(digest, hash_algorithm)` on the `PKCS11Signer`, wrapped
  as CMS `SignedData` (detached, `ADOBE_PKCS7_DETACHED`) so it fits the container
  reserved at #4.1.
- Token discovery, PIN, slot selection, locks, and timeouts (`token_utils.py`)
  are reused unchanged.
- The visible appearance is rendered **server-side** at preparation (#4.1), so
  the agent no longer stamps; verify visual parity with the POC's seal (#18).

This is the **single mandatory behavioural deviation from the POC** and must be
coordinated with the `pyhanko-bulksign` maintainers. The alternative that keeps
the POC agent unchanged (whole-PDF signing) is recorded in #16 and #18.

---

## 8. Completion processing

The DSC completion service (`apps.esign.services.completion`) factors the body of
the C-DAC `callback._complete()` so both paths share embed + store + success:

### 8.1 Trust before embed

DSC trust derives from the **authenticated session** (the caller owns the
transaction) and the **digest binding** (the PKCS#7 is only usable against the
exact prepared bytes — `_reserved_region` rejects a modified prepared PDF). There
is no response signature to verify; `verify_response` is a no-op for DSC (#3).

The PKCS#7 is validated structurally before embedding (reusing
`apps.pdf.services.signing._validated_pkcs7`): non-empty base64, CMS
`SignedData`, ≥1 signer, and it must fit the reserved container.

### 8.2 Idempotency and concurrency

Identical to [0015](0015-cdac-esign.md) #8.2: `select_for_update` on the
transaction, the `PENDING → SIGNING` gate, embed + upload outside the lock, then
a compare-and-set on `SIGNING` before `mark_success`. The unique
`(provider, provider_transaction_id)` pair guarantees at most one `signed_file_id`
per transaction however many times `_complete` is called.

---

## 9. Failure, expiry, and recovery

Reused from [0015](0015-cdac-esign.md) #9. A DSC transaction whose signer
abandons the token step stays `PENDING` and is swept to `EXPIRED` by the existing
sweeper at `expires_at + grace`. A row stuck in `SIGNING` (process died between
embed and success) is reconciled to `FAILURE` by the existing reconciler, and the
placeholder is retained for a retry. The placeholder-cleanup task applies
unchanged.

---

## 10. Error codes

All reused from [0015](0015-cdac-esign.md) #10 / `apps.esign.constants`; **no new
codes** are introduced:

| Code | HTTP | When |
| --- | --- | --- |
| `ESIGN_NOT_A_PDF` | 400 | source is not a PDF (initiation). |
| `ESIGN_INVALID_PLACEHOLDER` | 400 | placement does not fit the page. |
| `ESIGN_NOT_PERMITTED` | 403 | caller may not sign the entity. |
| `ESIGN_SOURCE_NOT_FOUND` | 404 | `file_id` resolves to nothing. |
| `ESIGN_ALREADY_IN_PROGRESS` | 409 | a live transaction already covers the document. |
| `ESIGN_SIGNATURE_MISSING` | 400 | `pkcs7` absent/empty. |
| `ESIGN_SIGNATURE_INVALID` | 400 | `pkcs7` not decodable / not CMS SignedData. |
| `ESIGN_RESPONSE_STALE` | 400 | `_complete` arrived past `expires_at + grace`. |
| `ESIGN_TRANSACTION_NOT_FOUND` | 404 | unknown id, or not the caller's. |
| `ESIGN_TRANSACTION_NOT_PROCESSABLE` | 409 | terminal row, or non-DSC provider. |
| `ESIGN_PDF_EMBED_FAILED` | 502 | container too small / field missing. |
| `ESIGN_SIGNED_UPLOAD_FAILED` | 502 | signed-PDF upload rejected/unavailable. |
| `ESIGN_PDF_PREPARATION_FAILED` | 502 | preparation failed (initiation). |
| `ESIGN_FILE_STORAGE_UNAVAILABLE` | 502 | storage unavailable. |
| `ESIGN_REQUEST_BUILD_FAILED` | 502 | provider could not build initiation. |
| `ESIGN_DISABLED` | 503 | kill switch. |
| `ESIGN_PROVIDER_NOT_CONFIGURED` | 503 | `ESIGN_PROVIDER` unset/invalid. |

`ESIGN_SIGNING_INTERRUPTED` (already defined) is used by the reconciler for a
stuck `SIGNING` row.

---

## 11. Configuration

New settings (declared in `config.settings.base`, `.env.example`,
`.env.prod.example`):

| Setting | Meaning |
| --- | --- |
| `ESIGN_PROVIDER` | dotted path of the active provider; DSC = `addon.dsc_esign.provider.DSCESignProvider`. |
| `DSC_AGENT_URL` | local agent sign URL returned as `esign_url` (default `http://localhost:1620/sign`). |
| `SIGNING_METHODS` *(or per-state config, `SGM-05`)* | enabled methods per state; drives which provider/UI option is offered. |

Reused unchanged: `ESIGN_ENABLED`, `ESIGN_TRANSACTION_TTL`,
`ESIGN_CALLBACK_GRACE_PERIOD`, `ESIGN_SIGNING_STUCK_TIMEOUT`,
`ESIGN_MAX_ATTEMPTS`, `PDF_SIGNATURE_CONTAINER_BYTES`,
`PDF_SIGNATURE_HASH_ALGORITHM`, `PDF_MAX_SIGN_INPUT_BYTES`.

Where C-DAC and DSC must coexist, `ESIGN_PROVIDER` is resolved per request from
the state's `signingMethods` rather than a single global value (#18).

### 11.1 Startup validation

A system check (like `addon.cdac_esign`) verifies, when DSC is enabled, that
`DSC_AGENT_URL` is a valid absolute URL and that `PDF_SIGNATURE_CONTAINER_BYTES`
is large enough for a DSC CMS including the CA chain.

---

## 12. Security

- **No key material on the server.** The token and PIN never leave the signer's
  machine; the backend handles only the public digest and the detached CMS. This
  is a security improvement over any server-side signing approach.
- **Completion is authenticated** and caller-owned — stronger than the anonymous
  C-DAC callback, which DSC does not reuse.
- **Local-agent hardening** (owned by `pyhanko-bulksign`): bind `127.0.0.1`,
  restrict `CORS_ALLOW_ORIGINS` to the court web origin(s).
- **Integrity:** the digest binds the signature to exact bytes; `_reserved_region`
  rejects a prepared PDF altered after preparation.
- **Audit redaction** reused from [0015](0015-cdac-esign.md) #12: only the
  certificate CN is stored, never the certificate or PKCS#7 blob; audit strings
  are truncated.
- **Trust of the certificate itself:** DSC certs must chain to India CCA roots to
  validate in viewers. Until a trust store + verification service exist (#17,
  #18), the stored PDF is cryptographically intact but shows UNTRUSTED. Whether
  to enforce CCA trust at `_complete` is an open question (#18).

---

## 13. Logging

Reused `EVENT_*` from [0015](0015-cdac-esign.md) #13: `ESIGN_INITIATED`,
`PDF_PREPARED`, `PLACEHOLDER_STORED`, `PROVIDER_REQUEST_BUILT`,
`SIGNATURE_EMBEDDED`, `SIGNED_STORED`, `ESIGN_SUCCEEDED`, `ESIGN_FAILED`,
`ESIGN_EXPIRED`. The DSC completion logs `SIGNATURE_EMBEDDED` / `SIGNED_STORED` /
`ESIGN_SUCCEEDED` exactly as the C-DAC callback does. No document bytes, digests,
certificates, or PKCS#7 content are ever logged.

---

## 14. Testing

- **Provider** (`addon.dsc_esign/tests`): `build_initiation` returns the agent
  URL and digest-bearing `form_fields`; `provider_transaction_id` shape;
  `verify_response` no-op.
- **Completion service**: happy path (embed + store + success) with a
  pyHanko-produced detached CMS over a prepared digest; invalid/empty `pkcs7`;
  container-too-small; stale; duplicate (`SUCCESS` returns existing); concurrent
  `SIGNING`; non-DSC provider rejected; not-caller rejected.
- **API**: envelope + `meta`; auth/permission; error codes; retry rebuilds the
  digest.
- **Integration**: end-to-end with a software (`.p12`) signer standing in for the
  token agent, producing a real detached CMS, through
  `prepare_for_signing → sign_raw → embed_signature`, and the signed PDF verified
  to carry one valid signature over the expected ByteRange.
- Reuse the 0015 fakes for `apps.pdf` / `apps.files`.

---

## 15. Acceptance criteria

1. With `ESIGN_PROVIDER` = DSC, `POST /esign/_esign` returns `esign_url =
   DSC_AGENT_URL` and `form_fields` containing the digest and field name.
2. `POST /esign/transactions/{id}/_complete` with a valid detached CMS over the
   prepared digest embeds the signature, stores the signed PDF, marks the
   transaction `SUCCESS`, and returns `signed_file_id`.
3. The resulting PDF carries exactly one valid signature over the expected
   ByteRange (software-signer integration test).
4. Duplicate `_complete` calls never produce a second signed file.
5. An invalid/oversized/stale PKCS#7 fails the transaction with the mapped code
   and a redacted, support-friendly audit.
6. C-DAC signing is unaffected: switching `ESIGN_PROVIDER` back restores the 0015
   flow with no code change.
7. No token, PIN, or PKCS#11 dependency is introduced into the backend.

---

## 16. Design decisions

1. **DSC is a provider, not a new subsystem.** It reuses the entire 0015
   lifecycle; only a provider class and one completion endpoint are added. This
   honours "avoid unnecessary APIs / don't duplicate signing".
2. **Detached CMS over the server digest (not whole-PDF).** The backend already
   owns prepare/embed via pyHanko; having the token produce a detached CMS keeps
   the server as the single producer of the authoritative signed file and makes
   dedup, retry, and audit work unchanged. Cost: the POC agent must change its
   output (#7.2).
3. **Authenticated JSON completion, not the anonymous callback.** DSC has no
   cross-site redirect; the signer's own session is present, so a JSON endpoint is
   simpler and safer than reusing the anonymous `/esign/_signed`.
4. **Synchronous.** No ESP wait and no queue; token latency is on the client.
5. **Bulk = client loop.** `SGM-02` signs "any number, on every document"; the
   browser iterates the single-document APIs with one PIN entry at agent START,
   as the POC already does. A server bulk endpoint is deferred (#18).

---

## 17. Out of scope

- The local agent's packaging, driver bundling, token discovery, and PIN/session
  handling (`pyhanko-bulksign`).
- Batch signing / batch certificates (`SGM-04`).
- India CCA trust-chain validation, RFC-3161 TSA, PAdES-LTV, and verification of
  previously signed PDFs.
- Server-side HSM/soft-certificate signing.
- Any new broker; the DSC main flow is synchronous.

---

## 18. Open questions

1. **Agent contract: detached CMS (#7.2, recommended) vs. whole signed PDF (POC
   as-is).** The latter avoids changing the agent but requires a new server-side
   validator that the signed PDF is an incremental update of the exact
   placeholder and that its embedded signature is valid — neither exists today.
   Which does the owner choose? *(Primary decision; blocks implementation.)*
2. **CCA trust enforcement** at `_complete` — reject non-CCA-chained certs, or
   store-and-warn initially? Who supplies and maintains the CCA trust store?
3. **RFC-3161 TSA / PAdES-LTV** — required now for long-term validity, or later?
4. **Signature appearance ownership** — server-rendered stamp (reuses
   `apps.pdf` appearance) vs. agent-rendered court seal; must the seal background
   be preserved? Confirm the **y-axis origin** against a real order PDF (POC open
   item).
5. **Multi-method configuration** — replace the single global `ESIGN_PROVIDER`
   with a per-state `signingMethods` resolver so C-DAC and DSC coexist (`SGM-05`).
6. **Bulk** — client loop (proposed) vs. a server bulk-convenience endpoint.
7. **Agent discovery/health** — should the UI probe `GET {agent}/health` before
   `_esign`, and is `esign_url` fixed by `DSC_AGENT_URL` or returned per request?

---

## 19. Implementation phases

1. **Provider** — `addon.dsc_esign` package: `DSCESignProvider`, constants,
   config, `resolve_config`, system check, unit tests.
2. **Completion service + endpoint** — factor `callback._complete()` into
   `apps.esign.services.completion`; add `DSCCompleteSerializer`, the
   `_complete` view, routing, Swagger, permission + provider guards; unit and API
   tests.
3. **Agent change** — coordinate the `pyhanko-bulksign` digest→CMS change (#7.2);
   integration test with a software signer standing in for the token.
4. **Configuration + multi-method** — `DSC_AGENT_URL`, `signingMethods`
   resolution so C-DAC and DSC coexist; env docs.
5. **Hardening and rollout** — security tests, redaction tests, end-to-end run
   against a real token on a signing machine; (follow-up) CCA trust, TSA.
