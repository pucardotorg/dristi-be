# 0015 — eSign Module and CDAC eSign Addon (`apps.esign` + `addon.cdac_esign`)

## Status

Proposed

## References

- [0000 — API Coding Spec](0000-api-coding-spec.md) — DRF/serializer/envelope constraints
- [0002 — Audit Fields Base Model](0002-audit-fields-base-model.md) — `apps.core.models.BaseModel`
- [0012 — Redis Caching](0012-redis-caching.md) — caching/exclusion rules
- [0014 — File Storage Service](0014-file-storage-service.md) — `apps.files`, owns document persistence and the `file_id` reference
- [0016 — PDF Service](0016-pdf-services.md) — `apps.pdf`, owns signature-container preparation and PKCS#7 embedding

> **Scope note.** The domain (transaction lifecycle, APIs, recovery, audit) lives
> in `apps.esign`. Everything CDAC-specific (eSign 2.1 XML, XMLDSig signing,
> response parsing, gateway form contract) lives in `addon.cdac_esign` behind a
> provider interface, exactly as 0013 does for SMS. PDF manipulation
> ([`apps.pdf`](0016-pdf-services.md)) and file persistence
> ([`apps.files`](0014-file-storage-service.md)) are **separate modules of this
> project**, consumed in-process through their published service functions; this
> spec neither implements nor re-specifies them.

## Context

Dristi must let a user electronically sign a PDF (order, judgment, filing,
vakalatnama) using the C-DAC eSign ESP, which performs Aadhaar eKYC + OTP in the
user's browser and returns a PKCS#7 signature to a callback URL.

Consequences that shape the design:

- Signing is a **three-legged browser flow**: our API returns form data, the
  browser leaves Dristi for C-DAC, and C-DAC POSTs back to our callback. State
  must therefore be persisted, correlated by a transaction ID, and recoverable.
- The hash sent to C-DAC is computed over a **PDF ByteRange of a prepared PDF**
  that already reserves an empty signature container. Preparation and embedding
  belong to the PDF Service module; this module only orchestrates.
- The callback is a **browser form POST**, not a JSON API call. It cannot carry
  our session/token auth and its response must be something a browser can
  render or follow.
- C-DAC can retry or replay the callback, so processing must be idempotent and
  concurrency-safe.

## Goals

- Own the eSign transaction lifecycle, state machine, and audit trail in
  `apps.esign`.
- Expose an initiation API, a callback endpoint, a status endpoint, and a retry
  action, all following 0000.
- Keep every C-DAC wire detail inside `addon.cdac_esign`, selected by a settings
  string, so a second ESP (or a mock) is a configuration change.
- Depend on the PDF Service and File Storage modules only through interfaces.
- Verify the C-DAC response cryptographically before trusting it.
- Make duplicate callbacks, partial failures, and abandoned transactions safe
  and recoverable.

## Non-goals

- Implementing PDF parsing, ByteRange computation, signature-container
  reservation, or PKCS#7 embedding (PDF Service module).
- Implementing document storage (File Storage module).
- Aadhaar authentication, OTP handling, or any C-DAC UI.
- DSC/HSM/token-based signing, bulk signing, long-term validation (LTV),
  timestamp authority (TSA) integration, or signature verification of
  previously signed documents.
- Kafka or any new broker. Redis/Dramatiq only, and only for the sweeper.

---

## 1. Module placement and dependency direction

```text
src/
├── apps/
│   ├── core/
│   ├── esign/                     # THIS SPEC — domain, models, APIs
│   ├── pdf/                       # 0016 — PDF Service (signing primitives)
│   ├── files/                     # 0014 — File Storage Service
│   └── ...
├── addon/
│   ├── cdac_sms_gateway/          # 0013
│   └── cdac_esign/                # THIS SPEC — CDAC wire protocol
└── config/settings/base.py        # the only wiring point
```

```text
addon.cdac_esign  -- imports -->  apps.esign (provider base class, dataclasses, exceptions)
apps.esign        -- never imports --> addon.*
apps.esign        -- imports -->  apps.pdf / apps.files *service functions only*
config.settings   -- references --> "addon.cdac_esign.provider.CDACESignProvider"
```

`apps.esign` is a normal domain app (models + migrations + DRF routes).
`addon.cdac_esign` is an installed app only so it can register system checks; it
contributes no models, migrations, URLs, or admin. Deleting
`src/addon/cdac_esign/` plus its settings entries must leave `apps.esign`
working on the mock provider.

### 1.1 Layout

```text
src/apps/esign/
├── apps.py                      # name = "apps.esign"
├── models.py                    # ESignTransaction
├── serializers.py
├── views.py                     # initiate, callback, status, retry
├── urls.py
├── admin.py
├── constants.py                 # statuses, error codes, log events
├── exceptions.py
├── providers/
│   ├── base.py                  # ESignProvider ABC + request/response dataclasses
│   ├── registry.py              # get_provider() via ESIGN_PROVIDER setting
│   └── mock.py                  # MockESignProvider (local/test default)
├── services/
│   ├── initiation.py
│   ├── callback.py
│   └── recovery.py
├── clients/
│   ├── pdf.py                   # adapter over apps.pdf signing services (0016)
│   └── files.py                 # adapter over apps.files services (0014)
├── tasks.py                     # expiry sweeper, placeholder cleanup
├── migrations/
└── tests/

src/addon/cdac_esign/
├── apps.py                      # name = "addon.cdac_esign", label = "cdac_esign"
├── provider.py                  # CDACESignProvider(ESignProvider)
├── config.py                    # CDACESignConfig, resolve_config() (cached, redacting repr)
├── request_builder.py           # <Esign> 2.1 XML
├── xml_signer.py                # enveloped XMLDSig using ASP key
├── response_parser.py           # <EsignResp> parsing
├── response_verifier.py         # XMLDSig verification against the CDAC cert
├── keystore.py                  # PKCS#12 loading from deployment secrets
├── constants.py                 # CDAC error/result codes, XML names
├── checks.py                    # Django system checks
└── tests/
```

---

## 2. End-to-end flow

```text
Dristi UI
   |  POST /api/v1/esign/_esign  {entity, file_id, sign_placeholder}
   v
apps.esign initiation service
   |
   +-- files.get_content(file_id)                        [apps.files, 0014]
   +-- pdf.prepare_for_signing(pdf, placeholder)         [apps.pdf, 0016]
   |        -> prepared_pdf, document_hash, field_name
   +-- files.upload(prepared_pdf)    -> placeholder_file_id
   +-- ESignTransaction.objects.create(status=PENDING)
   +-- provider.build_request(transaction, hash)         [addon.cdac_esign]
   |        -> <Esign ver="2.1"> XML, XMLDSig-signed with ASP key
   v
response: {esign_url, form_fields, transaction_id, cdac_transaction_id}
   |
   v
browser auto-submits form ---> C-DAC ESP ---> Aadhaar eKYC + OTP + consent
                                                   |
                                                   v
                        POST /api/v1/esign/_signed  (form-urlencoded, no session)
                                                   |
apps.esign callback service                        v
   +-- provider.parse_response(payload) -> ESignProviderResponse
   +-- provider.verify_response(payload)            (XMLDSig, CDAC cert)
   +-- lock transaction (select_for_update) -> status=SIGNING
   +-- files.get_content(placeholder_file_id)
   +-- pdf.embed_signature(prepared_pdf, pkcs7, field_name)
   +-- files.upload(signed_pdf) -> signed_file_id
   +-- status=SUCCESS
   v
HTTP 302 -> ESIGN_UI_REDIRECT_URL?transaction_id=..&status=SUCCESS
```

The source PDF is never modified or overwritten. Every artefact is a new
`apps.files` record with its own `file_id`.

---

## 3. Provider interface (`apps.esign.providers.base`)

```python
@dataclass(frozen=True)
class ESignInitiation:
    esign_url: str                 # ESP endpoint the browser posts to
    form_fields: dict[str, str]    # field name -> value, posted as-is
    provider_transaction_id: str   # correlation id echoed back by the ESP
    request_audit: dict            # non-sensitive request metadata to persist


@dataclass(frozen=True)
class ESignProviderResponse:
    provider_transaction_id: str
    success: bool
    signature: str | None          # base64 PKCS#7, present only on success
    signer_certificate: str | None # base64 X.509 of the signer
    error_code: str
    error_message: str
    signed_at: datetime | None
    response_audit: dict


class ESignProvider(ABC):
    name: ClassVar[str]

    @abstractmethod
    def build_initiation(self, transaction, document_hash: str) -> ESignInitiation: ...

    @abstractmethod
    def parse_response(self, payload: Mapping[str, str]) -> ESignProviderResponse: ...

    @abstractmethod
    def verify_response(self, payload: Mapping[str, str]) -> None:
        """Raise ESignResponseUntrusted if the ESP response is not authentic."""
```

Selection mirrors `MESSAGING_BACKENDS`:

```python
ESIGN_PROVIDER = "addon.cdac_esign.provider.CDACESignProvider"
# local/test default: "apps.esign.providers.mock.MockESignProvider"
```

`registry.get_provider()` resolves the string lazily with `import_string` and
caches it. An unset or unimportable provider raises
`ESignProviderNotConfigured`.

---

## 4. PDF Service and File Storage contracts consumed

Both modules are called **in-process** through their service functions, wrapped
in narrow adapters so the domain stays indifferent to their internals (and to a
future REST layer, which `apps.esign` would still not use).

### 4.1 PDF Service (`apps.pdf`, [`0016`](0016-pdf-services.md) #14)

```python
# apps/esign/clients/pdf.py — adapter over apps.pdf.services.signing
class PDFClient(Protocol):
    def prepare_for_signing(
        self, document: bytes, placeholder: dict
    ) -> PreparedDocument:
        """Reserve an empty signature container and return the ByteRange hash.

        Returns prepared_document (bytes), document_hash (hex digest over the
        PDF ByteRange, algorithm per PDF_SIGNATURE_HASH_ALGORITHM), field_name.
        """

    def embed_signature(
        self, prepared_document: bytes, pkcs7: bytes, field_name: str
    ) -> bytes:
        """Insert the PKCS#7 blob into the reserved container. Returns the signed PDF."""
```

Requirements placed on 0016 by this spec: create a signature field, reserve a
container large enough for a C-DAC PKCS#7 blob, compute the ByteRange digest,
accept a detached PKCS#7, produce a valid signed PDF, and preserve existing
signatures when a document is signed more than once (incremental update). These
are synchronous, bytes-in/bytes-out functions: no `PDFJob` row is created and
`apps.pdf` neither stores nor fetches the document.

### 4.2 File Storage Service (`apps.files`, [`0014`](0014-file-storage-service.md) #2)

```python
# apps/esign/clients/files.py — adapter over apps.files.services
class FileClient(Protocol):
    def get_metadata(self, file_id: str) -> dict: ...   # get_file(): content_type, size, ...
    def get_content(self, file_id: str) -> bytes: ...   # get_file_content()
    def upload(self, content: bytes, *, filename: str,
               file_type: str, user_id: str, organization_id: str | None,
               tags: list[str]) -> str: ...             # upload_file() -> file_id
    def delete(self, file_id: str) -> None: ...         # delete_file(), cleanup only
```

Adapter responsibilities:

- Call `upload_file()` with the single-file batch shape of [`0014`](0014-file-storage-service.md) #3 and return the one `file_id`; the domain never sees the batch envelope.
- `file_type` is `FileType.PDF` for the placeholder and `FileType.SIGNED_PDF`
  for the signed output; tags are `esign`, the `module`, and the `entity_id`, so
  artefacts are discoverable through `search_file`.
- `user_id` is `transaction.signer_id`. The callback leg has **no authenticated
  request user**, so the signer captured at initiation — not the request — is the
  actor for the signed-PDF upload; when no signer is set, the configured system
  actor is used.
- Map module exceptions to `ESignPDFError` / `ESignFileStorageError`, enforce the
  configured size limits, and never log document bytes.

This spec depends on 0014 exposing `get_file_content()` and `delete_file()`; both
are required amendments there ([`0014`](0014-file-storage-service.md) #6.1, #6.2).

---

## 5. `ESignTransaction` model

Location: `apps.esign.models`. Inherits `apps.core.models.BaseModel` (UUID pk,
`created_at`/`updated_at`/`created_by`/`updated_by`).

| Field | Type | Notes |
| --- | --- | --- |
| `tenant_id` | `CharField(64)` | required |
| `module` | `CharField(64)` | initiating Dristi module/page (`pageModule` in the Java service) |
| `entity_type` | `CharField(64, blank=True)` | what is being signed, e.g. `order` |
| `entity_id` | `CharField(64, blank=True, db_index=True)` | id of that entity |
| `signer` | `FK(AUTH_USER_MODEL, null=True, on_delete=PROTECT)` | user who initiated signing |
| `provider` | `CharField(32)` | `ESignProvider.name`, e.g. `cdac` |
| `provider_transaction_id` | `CharField(128, unique=True)` | id sent to / echoed by the ESP |
| `source_file_id` | `CharField(64)` | `apps.files` id of the original PDF, never mutated |
| `placeholder_file_id` | `CharField(64, blank=True)` | `apps.files` id of the prepared PDF |
| `signed_file_id` | `CharField(64, blank=True)` | `apps.files` id of the final signed PDF |
| `sign_placeholder` | `JSONField(default=dict, blank=True)` | signature placement (#6.2) |
| `document_hash` | `CharField(128, blank=True)` | hex hash sent to the ESP |
| `signature_field_name` | `CharField(128, blank=True)` | returned by PDF Service |
| `status` | `CharField(16, choices=Status)` | #5.1 |
| `attempt_count` | `PositiveSmallIntegerField(default=1)` | ESP attempts for this document |
| `retry_of` | `FK("self", null=True, blank=True, on_delete=SET_NULL)` | previous failed/expired transaction |
| `request_audit` | `JSONField(default=dict, blank=True)` | non-sensitive request metadata |
| `response_audit` | `JSONField(default=dict, blank=True)` | ESP status/result/error, signer cert subject |
| `failure_code` | `CharField(64, blank=True)` | internal code (#10) |
| `failure_message` | `TextField(blank=True)` | safe, user-presentable detail |
| `expires_at` | `DateTimeField()` | initiation time + `ESIGN_TRANSACTION_TTL` |
| `callback_received_at` | `DateTimeField(null=True, blank=True)` | first callback |
| `completed_at` | `DateTimeField(null=True, blank=True)` | reached `SUCCESS` |

`Meta.ordering = ["-created_at"]`.

Neither the PKCS#7 blob, the signed XML request, the raw callback body, nor any
key material is stored on the model. `request_audit`/`response_audit` hold codes
and metadata only.

### 5.1 State machine

```text
PENDING ──callback accepted──> SIGNING ──signed PDF stored──> SUCCESS
   │                              │
   │                              └── any failure ──> FAILURE
   ├── TTL elapsed, no callback ──> EXPIRED
   └── any pre-callback failure ──> FAILURE
```

| Status | Meaning |
| --- | --- |
| `PENDING` | prepared PDF stored, ESP request issued, awaiting callback |
| `SIGNING` | callback accepted and being processed (concurrency guard) |
| `SUCCESS` | signature embedded and signed PDF stored — terminal |
| `FAILURE` | could not complete; placeholder retained for retry |
| `EXPIRED` | no callback within TTL; retryable |

Rules:

- `SUCCESS` is terminal. No transition leaves it.
- `SIGNING` is only enterable from `PENDING` under `select_for_update()`.
- `FAILURE` and `EXPIRED` never transition; **retry creates a new row** with
  `retry_of` set and the same `placeholder_file_id` (#9). This keeps
  `provider_transaction_id` unique and preserves every attempt for audit.
- Transitions are enforced in a model method (`mark_signing()`, `mark_success()`,
  `mark_failed()`, `mark_expired()`); illegal transitions raise
  `ESignInvalidTransition`.

### 5.2 Constraints and indexes

- `UniqueConstraint("provider_transaction_id")`.
- `CheckConstraint`: `status != SUCCESS OR signed_file_id != ""`.
- `CheckConstraint`: `status NOT IN (SIGNING, SUCCESS) OR placeholder_file_id != ""`.
- Index on `(status, expires_at)` for the sweeper.
- Index on `(entity_type, entity_id)` and `(tenant_id, created_at)` for lookups.
- Non-DB invariants (placement validity, hash format) live in `clean()`.

---

## 6. APIs

All routes live in `apps/esign/urls.py`, are included under `/api/v1/`, are
tagged `esign` in Swagger, and carry the standard `meta` envelope — except the
callback, which is not a JSON API (#6.3).

### 6.1 `POST /api/v1/esign/_esign` — initiate

Authenticated (`IsAuthenticated`). Request:

```json
{
  "tenant_id": "kl",
  "module": "orders",
  "entity_type": "order",
  "entity_id": "9f2c...",
  "file_id": "abc-123",
  "sign_placeholder": {
    "page": 1,
    "position": "bottom-right",
    "x": 380, "y": 60, "width": 160, "height": 60,
    "reason": "Approved", "location": "District Court, Ernakulam"
  }
}
```

Serializer validation: required scalars present; `file_id` resolves through
`get_file()`; its `content_type` is `application/pdf`; `sign_placeholder` matches the
declared schema and page/coordinates are within the document; the requesting
user is permitted to sign the referenced entity (object-level permission
delegated to the owning module, not hardcoded here).

Response `201`:

```json
{
  "transaction_id": "0f9d...",
  "provider_transaction_id": "kl-orders-0f9d...",
  "expires_at": "2026-09-22T18:10:00+05:30",
  "esign_url": "https://esign.cdac.in/...",
  "form_method": "POST",
  "form_fields": {
    "eSignRequest": "<base64 signed XML>",
    "aspTxnID": "kl-orders-0f9d...",
    "Content-Type": "application/xml"
  },
  "meta": { "timestamp": "...", "app_version": "...", "spec_version": "1.0" }
}
```

The UI treats `form_fields` as opaque and posts them verbatim to `esign_url`.
No provider-specific knowledge in the client.

### 6.2 `GET /api/v1/esign/transactions/{id}` — status

Authenticated; scoped to the initiating user/tenant. Returns status,
`signed_file_id` when `SUCCESS`, `failure_code`/`failure_message`
otherwise. This is the endpoint the UI polls after the browser returns, and it
is the only supported way for a client to learn the outcome. Excluded from
caching (per [`0012`](0012-redis-caching.md)) because it is read-after-write on a
volatile row.

### 6.3 `POST /api/v1/esign/_signed` — ESP callback

- `AllowAny`, `@csrf_exempt`, authentication classes emptied. Trust comes from
  the response signature, not from the caller.
- Accepts `application/x-www-form-urlencoded` (and `application/xml`), because
  C-DAC posts a browser form.
- The transaction is identified **only** from the verified ESP response. Any
  client-supplied `file_id`, transaction id, or redirect target in the query
  string is ignored.
- Response is a `302` to `ESIGN_UI_REDIRECT_URL` with
  `transaction_id` and `status` query parameters (allow-listed host, configured
  server-side — never taken from the request). If no redirect URL is configured,
  return a minimal HTML page. A JSON `meta` envelope is explicitly not used
  here; this is documented in the Swagger annotation.
- Throttled per IP, and payload size limited, since the endpoint is public.

### 6.4 `POST /api/v1/esign/transactions/{id}/_retry` — retry

Authenticated. Creates a new transaction from a `FAILURE`/`EXPIRED` one, reusing
the existing placeholder PDF, and returns the same body as #6.1. Rejects retry
of `PENDING`/`SIGNING`/`SUCCESS` rows and enforces `ESIGN_MAX_ATTEMPTS`.

---

## 7. CDAC wire contract (`addon.cdac_esign`)

### 7.1 Request XML (eSign API 2.1)

```xml
<Esign ver="2.1" sc="Y" ts="2026-09-22T17:40:03" txn="kl-orders-0f9d..."
       ekycIdType="A" aspId="ASP-ID" AuthMode="1"
       responseSigType="pkcs7" responseUrl="https://.../api/v1/esign/_signed">
  <Docs>
    <InputHash id="1" hashAlgorithm="SHA256"
               docInfo="Order 9f2c..." docUrl="">HEX_HASH</InputHash>
  </Docs>
</Esign>
```

- `ver="2.1"`, `hashAlgorithm="SHA256"`, `AuthMode="1"` (Aadhaar OTP),
  `ekycIdType="A"`, `responseSigType="pkcs7"`, `sc="Y"` (consent) are the
  defaults; each is a config key so C-DAC can change them without code changes.
- `ts` is IST, `yyyy-MM-dd'T'HH:mm:ss`, with no timezone suffix, taken from the
  same clock source as `expires_at`.
- `txn` is `provider_transaction_id`; format
  `{tenant_id}-{module}-{transaction_uuid}` truncated to the ESP limit, with the
  template configurable. The UUID keeps it collision-free and traceable.
- `InputHash` is the hex digest supplied by the PDF Service. The document itself
  is never sent to C-DAC.
- The structure supports multiple `InputHash` elements; this iteration emits
  exactly one and the parser rejects a response carrying a different count.

### 7.2 Request signing

The XML is signed with an **enveloped XMLDSig** signature (`signxml` or
`xmlsec`) using the ASP private key and certificate loaded from a PKCS#12
keystore: exclusive canonicalisation, SHA-256 digest, RSA-SHA256 signature,
enveloped transform, and the ASP `X509Certificate` in `KeyInfo`. The signed XML
is then base64-encoded into the `eSignRequest` form field.

Key material is loaded once from deployment-managed secrets (file path or
injected value), cached in memory, never written to the DB, Git, logs, API
responses, or `request_audit`, and the config dataclass redacts it in `repr`.

### 7.3 Response

```xml
<EsignResp status="1" ts="..." txn="kl-orders-0f9d..." resCode="..."
           errCode="" errMsg="">
  <UserX509Certificate>BASE64</UserX509Certificate>
  <Signatures><DocSignature id="1" error="">BASE64_PKCS7</DocSignature></Signatures>
</EsignResp>
```

Parsing rules:

- `status == "1"` is success; anything else is failure with `errCode`/`errMsg`
  mapped to an internal failure code and a generic user-facing message.
- Success requires a non-empty `DocSignature` with empty `error`; otherwise
  `ESIGN_SIGNATURE_MISSING`.
- `DocSignature` content must decode from base64 and parse as a PKCS#7
  structure before being handed to the PDF Service.
- The `UserX509Certificate` subject/serial are recorded in `response_audit`;
  the full certificate is not persisted.
- Unknown extra elements are ignored; unparsable XML is
  `ESIGN_CALLBACK_MALFORMED`.

---

## 8. Callback processing

```text
raw form POST
   |
   +-- 1. parse payload            -> ESignProviderResponse
   +-- 2. verify_response()        -> XMLDSig valid against configured CDAC cert
   +-- 3. lookup by provider_transaction_id (select_for_update)
   +-- 4. state gate (#8.2)
   +-- 5. mark SIGNING, commit                         [tx 1]
   +-- 6. files.get_content(placeholder) ; pdf.embed_signature ; files.upload
   +-- 7. mark SUCCESS + signed_file_id                [tx 2]
   v
302 -> UI
```

External calls sit **between** two short DB transactions rather than inside one,
because a network call cannot participate in a Postgres transaction and must not
hold a row lock. `SIGNING` is the durable marker that makes step 6 recoverable.

### 8.1 Verification before trust

A callback is rejected unless **all** of these hold:

1. The response XMLDSig verifies against the configured C-DAC certificate
   (`CDAC_ESIGN_RESPONSE_CERT`), with the expected digest/signature algorithms.
2. `txn` is present and matches an existing `provider_transaction_id`.
3. `ts` is within `CDAC_ESIGN_RESPONSE_MAX_SKEW` of now.
4. The transaction has not expired beyond `ESIGN_CALLBACK_GRACE_PERIOD`.
5. The payload is well-formed and the signature count matches the request.

Signature verification is mandatory in production (a system check enforces that
the certificate is configured) and may be disabled only in local/test.

### 8.2 Idempotency and concurrency

| Current status | Behaviour |
| --- | --- |
| `PENDING` | process normally |
| `SIGNING` | another worker holds it — return the redirect without reprocessing |
| `SUCCESS` | no-op; redirect with `status=SUCCESS` (never produce a second signed file) |
| `FAILURE` / `EXPIRED` | reject with `ESIGN_TRANSACTION_NOT_PROCESSABLE`; the user must retry explicitly |

`select_for_update()` on the status gate serialises concurrent callbacks; the
first wins and the rest observe a non-`PENDING` status. Combined with the unique
`provider_transaction_id` this guarantees at most one signed file per
transaction.

### 8.3 Interceptor deployments

If the deployment terminates C-DAC traffic at a separate interceptor, the
interceptor may only do transport/auth/allow-listing and must forward the
unmodified payload to `/api/v1/esign/_signed`. The business logic is identical
in both models; nothing in `apps.esign` branches on it.

---

## 9. Failure, expiry, and recovery

- Any failure before the transaction row exists returns a DRF error and stores
  nothing.
- Any failure after it exists sets `FAILURE` with `failure_code` and a safe
  `failure_message`, keeps `placeholder_file_id`, and leaves the source
  document untouched.
- The placeholder PDF is **retained** on failure so a retry does not re-prepare
  the source. Deletion happens only through the cleanup policy below.
- `tasks.expire_stale_transactions` (Dramatiq, periodic) moves `PENDING` rows
  past `expires_at` + grace to `EXPIRED`.
- `tasks.cleanup_placeholders` (Dramatiq, periodic) calls `delete_file()` for the
  placeholder files of terminal transactions older than
  `ESIGN_PLACEHOLDER_RETENTION` and clears the id. Never deletes source or
  signed files.
- `tasks.reconcile_signing_transactions` handles the crash window in #8: a row
  stuck in `SIGNING` past a timeout is moved to `FAILURE` with
  `ESIGN_SIGNING_INTERRUPTED`, so the retry path (not a partial write) resolves
  it. Because `signed_file_id` is written in the same transaction as `SUCCESS`, a
  crash between upload and commit can leave an orphaned `apps.files` record; it
  is unreferenced and left to the storage module's retention policy.
- Retry (#6.4) creates a new row: new `provider_transaction_id`, `retry_of` set,
  `attempt_count = parent.attempt_count + 1`, same placeholder and hash. The
  placeholder is only re-prepared if it is missing.

---

## 10. Error codes

`apps.esign.constants`:

```text
Initiation: ESIGN_INVALID_REQUEST, ESIGN_SOURCE_NOT_FOUND, ESIGN_NOT_A_PDF,
            ESIGN_INVALID_PLACEHOLDER, ESIGN_NOT_PERMITTED,
            ESIGN_PDF_PREPARATION_FAILED, ESIGN_FILE_STORAGE_UNAVAILABLE,
            ESIGN_PROVIDER_NOT_CONFIGURED, ESIGN_REQUEST_BUILD_FAILED,
            ESIGN_REQUEST_SIGNING_FAILED
Callback:   ESIGN_CALLBACK_MALFORMED, ESIGN_RESPONSE_UNTRUSTED,
            ESIGN_RESPONSE_STALE, ESIGN_TRANSACTION_NOT_FOUND,
            ESIGN_TRANSACTION_NOT_PROCESSABLE, ESIGN_PROVIDER_REJECTED,
            ESIGN_SIGNATURE_MISSING, ESIGN_SIGNATURE_INVALID,
            ESIGN_PDF_EMBED_FAILED, ESIGN_SIGNED_UPLOAD_FAILED,
            ESIGN_SIGNING_INTERRUPTED
Retry:      ESIGN_NOT_RETRYABLE, ESIGN_MAX_ATTEMPTS_EXCEEDED,
            ESIGN_PLACEHOLDER_MISSING
```

C-DAC `errCode` values are mapped to these in `addon/cdac_esign/constants.py`;
the raw code is kept in `response_audit` for support. API responses never expose
key material, stack traces, raw ESP payloads, or infrastructure details.

---

## 11. Configuration

Domain settings (`apps.esign`), `ESIGN_` prefix:

| Setting | Default | Notes |
| --- | --- | --- |
| `ESIGN_PROVIDER` | mock | dotted path to the provider class |
| `ESIGN_ENABLED` | `True` | kill switch; initiation returns 503 when off |
| `ESIGN_TRANSACTION_TTL` | `900` s | drives `expires_at` |
| `ESIGN_CALLBACK_GRACE_PERIOD` | `300` s | late-callback tolerance |
| `ESIGN_SIGNING_STUCK_TIMEOUT` | `300` s | reconciliation threshold |
| `ESIGN_MAX_ATTEMPTS` | `3` | per source document |
| `ESIGN_PLACEHOLDER_RETENTION` | `7` d | cleanup policy |
| `ESIGN_UI_REDIRECT_URL` | `""` | server-side allow-listed redirect target |
| `ESIGN_CALLBACK_THROTTLE_RATE` | `60/min` | public endpoint protection |

Addon settings (`addon.cdac_esign`), `CDAC_ESIGN_` prefix — matching the
`CDAC_SMS_` convention of 0013:

| Setting | Required | Notes |
| --- | --- | --- |
| `CDAC_ESIGN_URL` | yes | ESP endpoint the browser posts to |
| `CDAC_ESIGN_ASP_ID` | yes | ASP identifier |
| `CDAC_ESIGN_RESPONSE_URL` | yes | absolute `https://` callback URL |
| `CDAC_ESIGN_KEYSTORE_PATH` | yes | PKCS#12 with ASP key + cert |
| `CDAC_ESIGN_KEYSTORE_PASSWORD` | yes | secret; never logged |
| `CDAC_ESIGN_RESPONSE_CERT` | yes (prod) | C-DAC cert used to verify responses |
| `CDAC_ESIGN_VERSION` | no (`2.1`) | |
| `CDAC_ESIGN_AUTH_MODE` | no (`1`) | Aadhaar OTP |
| `CDAC_ESIGN_HASH_ALGORITHM` | no (`SHA256`) | must match PDF Service digest |
| `CDAC_ESIGN_EKYC_ID_TYPE` | no (`A`) | |
| `CDAC_ESIGN_CONSENT` | no (`Y`) | |
| `CDAC_ESIGN_TXN_TEMPLATE` | no | `{tenant_id}-{module}-{transaction_id}` |
| `CDAC_ESIGN_RESPONSE_MAX_SKEW` | no (`900` s) | `ts` freshness window |
| `CDAC_ESIGN_VERIFY_RESPONSE_SIGNATURE` | no (`True`) | rejected as `False` in production |

`resolve_config()` returns a cached frozen dataclass with a redacting `__repr__`.
Every setting is documented in `.env.example`, `.env.prod.example`, and
`README.md`.

### 11.1 Startup validation

System checks registered in each app's `AppConfig.ready()`, so
`python manage.py check` fails fast in containers. Error level when
`CDACESignProvider` is the active provider and eSign is enabled:

- all required `CDAC_ESIGN_*` values present;
- `CDAC_ESIGN_URL` and `CDAC_ESIGN_RESPONSE_URL` are absolute `https://` URLs;
- keystore exists, opens with the given password, and holds a key + cert;
- ASP certificate is not expired (warning within 30 days of expiry);
- `CDAC_ESIGN_HASH_ALGORITHM` matches `PDF_SIGNATURE_HASH_ALGORITHM`
  ([`0016`](0016-pdf-services.md) #15), since the ESP is told which algorithm
  produced the hash it receives;
- production: response-signature verification enabled, response cert present,
  mock provider not selected, `ESIGN_UI_REDIRECT_URL` set and `https://`.

Checks are silent when the addon is installed but not the active provider, so
local/CI need no C-DAC credentials or keystore.

---

## 12. Security

- The callback is unauthenticated by necessity; authenticity comes solely from
  XMLDSig verification, `txn` correlation, timestamp freshness, and state gating.
- A callback can never select a different document: the `file_id`s come from the
  stored transaction, never from the request.
- Redirect targets are server-side configuration, preventing open redirect.
- ASP key material: secrets-injected, memory-cached, never persisted, logged,
  returned, or serialised.
- Never logged: private key, keystore password, Aadhaar number, OTP, signed
  request XML, raw callback body, PKCS#7 blob, document bytes.
- Status and retry endpoints are scoped so one user cannot read or retry another
  user's transaction.
- Public callback is throttled and body-size limited.
- Transaction rows are excluded from ORM caching to avoid stale status reads.

---

## 13. Logging

One structured line per stage on the `apps.esign` / `addon.cdac_esign` loggers,
always carrying `transaction_id`, `provider_transaction_id`, `tenant_id`,
`module`, and `status`:

```text
ESIGN_INITIATED, PDF_PREPARED, PLACEHOLDER_STORED, PROVIDER_REQUEST_BUILT,
CALLBACK_RECEIVED, CALLBACK_VERIFIED, CALLBACK_REJECTED, SIGNATURE_EMBEDDED,
SIGNED_STORED, ESIGN_SUCCEEDED, ESIGN_FAILED, ESIGN_EXPIRED, ESIGN_RETRIED
```

Monitoring uses these plus `ESignTransaction` aggregates: counts by `status` and
`failure_code`, `PENDING`→`SUCCESS` latency, expiry rate, retry rate. No
dedicated metrics backend in this iteration.

---

## 14. Testing

**Unit (no network, providers/clients mocked)**
- model: legal and illegal transitions, `SUCCESS` terminality, constraints,
  unique `provider_transaction_id`, `clean()` invariants.
- request builder: every required attribute/value, IST timestamp format, hex hash
  placement, txn template and truncation, single `InputHash`.
- XML signer: enveloped signature present, algorithms, cert in `KeyInfo`,
  missing/invalid keystore handling.
- response parser: success, `status != 1`, empty `DocSignature`, `error`
  attribute set, malformed XML, signature-count mismatch, non-base64 payload.
- response verifier: valid signature, tampered XML, wrong cert, stale `ts`.
- config/checks: defaults, missing required keys, redacted repr, each check
  failure mode, silence when the addon is inactive, production guards.
- initiation service: happy path, missing source, non-PDF, invalid placeholder,
  PDF Service failure, File Storage failure, provider build failure, permission
  denial — and that a transaction row exists with the right terminal state.
- callback service: unknown txn, untrusted signature, stale timestamp, provider
  rejection, missing signature, embed failure, upload failure.

**Integration (DB + stub broker, PDF/File Storage/provider mocked)**
- full flow: initiate → callback → `SUCCESS` with a `signed_file_id`, and
  a source file that is byte-identical afterwards.
- duplicate callback: second delivery produces no second signed file and returns
  the same redirect.
- concurrent callbacks: two parallel requests, exactly one embed call.
- expiry sweeper, `SIGNING` reconciliation, placeholder cleanup.
- retry: new row, `retry_of` chain, placeholder reused, `ESIGN_MAX_ATTEMPTS`.
- API contract: `meta` envelope on JSON endpoints, callback returns a 302 (and
  is exempt from the envelope), auth/permission behaviour, throttling.
- isolation: no module under `apps.esign` imports `addon.*`; deleting the addon
  leaves the app working on the mock provider.

**Security**
- key material absent from responses, logs, and DB rows;
- callback cannot target another document or transaction;
- a `SUCCESS` transaction cannot be re-signed;
- redirect target cannot be influenced by the request.

**Manual / end-to-end** against the C-DAC test ESP: real Aadhaar OTP flow, real
callback, signed PDF opens in a PDF reader with a valid signature covering the
whole document, and the source PDF unchanged.

```bash
cd src && DJANGO_SETTINGS_MODULE=config.settings.test pytest
cd src && ruff check . && ruff format .
cd src && python manage.py check
```

---

## 15. Affected files

New (`apps.esign`): app package per #1.1 plus migrations and tests.

New (addon): `src/addon/cdac_esign/{__init__,apps,provider,config,request_builder,xml_signer,response_parser,response_verifier,keystore,constants,checks}.py` and `tests/`.

Modified (other modules, as amendments to their own specs):
- `src/apps/files/services.py` — `get_file_content()`, `delete_file()`, and the `SIGNED_PDF` file type per [`0014`](0014-file-storage-service.md) #1.2/#6.1/#6.2
- `src/apps/pdf/services/signing.py` — `prepare_for_signing()` / `embed_signature()` per [`0016`](0016-pdf-services.md) #14

Modified (wiring and docs):
- `src/config/settings/base.py` — `INSTALLED_APPS` (`apps.esign`, `addon.cdac_esign`), `ESIGN_*` and `CDAC_ESIGN_*` blocks
- `src/config/settings/local.py`, `test.py` — mock provider default
- `src/config/settings/production.py` — production guards
- `src/config/urls.py` — include `apps.esign.urls` under `/api/v1/`
- `src/requirements/*` — `signxml`/`xmlsec`, `cryptography`
- `.env.example`, `.env.prod.example`, `README.md`
- `AGENTS.md` — note that `addon.*` now hosts two integrations

Depends on: [`0016`](0016-pdf-services.md) #14 (`prepare_for_signing`,
`embed_signature`) and [`0014`](0014-file-storage-service.md) #6.1/#6.2
(`get_file_content`, `delete_file`). Neither dependency is duplicated here.

---

## 16. Acceptance criteria

- [ ] `apps.esign` owns the model, state machine, APIs, recovery, and audit.
- [ ] All C-DAC specifics live in `addon.cdac_esign`; `apps.esign` never imports `addon.*`.
- [ ] Provider is selected purely by `ESIGN_PROVIDER`; the mock provider is the local/test default.
- [ ] No PDF parsing or file persistence code exists in this module; `apps.pdf` and `apps.files` are used through their service functions only.
- [ ] Initiation prepares the PDF, stores the placeholder, creates a `PENDING` row, and returns opaque `form_fields` + `esign_url`.
- [ ] Source document is never modified; placeholder and signed PDFs are new `apps.files` records.
- [ ] Request XML matches #7.1 and is enveloped-XMLDSig signed with the ASP key from a PKCS#12 keystore.
- [ ] Callback is `AllowAny` + CSRF-exempt, accepts form-urlencoded, verifies the response signature, and returns a 302 to a server-configured URL.
- [ ] Verification rejects untrusted, stale, malformed, unknown, or non-processable callbacks.
- [ ] Transaction is identified only from the verified response; request-supplied ids are ignored.
- [ ] Duplicate and concurrent callbacks produce exactly one signed file.
- [ ] `SUCCESS` always carries a `signed_file_id` (DB-enforced).
- [ ] Failures record `failure_code`/`failure_message`, retain the placeholder, and are retryable.
- [ ] Retry creates a new transaction linked by `retry_of`, bounded by `ESIGN_MAX_ATTEMPTS`.
- [ ] Sweeper expires stale `PENDING` rows and reconciles stuck `SIGNING` rows.
- [ ] `manage.py check` fails on invalid eSign/C-DAC configuration and is silent when the addon is inactive.
- [ ] Key material, Aadhaar data, OTP, PKCS#7, and document bytes never appear in logs, DB, or API responses.
- [ ] JSON endpoints carry the `meta` envelope, are tagged `esign`, and are documented in `drf-spectacular` (callback documented as a non-envelope redirect).
- [ ] Unit, integration, security, and isolation tests pass; Ruff clean.
- [ ] No Kafka dependency; Dramatiq/Redis used only for the periodic tasks.

---

## 17. Design decisions

| Decision | Rationale |
| --- | --- |
| Domain in `apps.esign`, wire protocol in `addon.cdac_esign` | Mirrors 0009/0013. The transaction lifecycle is a Dristi domain concern that outlives any ESP; the XML and keystore are swappable integration detail. |
| Provider interface instead of a bare CDAC client | Gives a mock provider for local/CI without C-DAC credentials, and makes a second ESP a settings change. |
| PDF and storage consumed via narrow adapters | `apps.pdf` and `apps.files` are separate modules of this project; adapters keep the domain indifferent to their internals and to any future REST layer. |
| Signing primitives live in `apps.pdf`, not here | Container reservation and the ByteRange digest are PDF-format concerns belonging to the module that already owns PDF bytes; duplicating them would guarantee drift. `apps.pdf` in turn holds no keys and never talks to an ESP. |
| PDF Service computes the hash | The digest is defined over the PDF ByteRange, which only the module reserving the container can compute. Duplicating it here would guarantee drift. |
| Extra `SIGNING` state | External calls cannot run inside a DB transaction; a durable in-progress marker is what makes crash recovery and concurrency safety possible. |
| `EXPIRED` state + sweeper | The common real-world outcome is a user abandoning the C-DAC screen. Without it, `PENDING` grows forever and retry eligibility is undefined. |
| Retry creates a new row, not a mutation | `provider_transaction_id` is unique and each ESP attempt has its own id and audit trail; mutating in place would destroy history and break the constraint. |
| Response XMLDSig verification is mandatory | The callback is a public, unauthenticated endpoint. Without verification, anyone who learns a `txn` could inject a signature. This was the largest gap in the original draft. |
| Callback returns a 302, not a `meta` envelope | The caller is a browser mid-navigation, not an API client. Forcing the JSON envelope here would leave the user staring at raw JSON. |
| Redirect URL is server-side config | Taking it from the request would make a public endpoint an open redirect. |
| Status endpoint is the UI's source of truth | The browser leaves the app during signing, so the outcome must be fetchable after return rather than pushed. |
| Placeholder retained on failure, cleaned by policy | Re-preparing the source on every retry wastes work and risks a different hash; unbounded retention wastes storage. |
| Provider transaction id embeds the internal UUID | Guarantees uniqueness and makes support lookups trivial in both systems. |
| Single `InputHash` this iteration | Multi-document signing needs its own model (one transaction, many documents) and is deferred rather than half-supported. |

## 18. Out of scope

- PDF Service and File Storage implementations.
- Multi-document / bulk signing in one C-DAC transaction.
- DSC/HSM/token signing, TSA timestamps, LTV, signature verification of existing PDFs.
- Additional ESPs, ESP failover, or DB-managed ESP configuration.
- Signature appearance rendering beyond the placement data passed to the PDF Service.
- Aadhaar/OTP handling, C-DAC UI, and any consent-artefact archival requirement.
- Asynchronous (queue-based) signing of the main flow; only maintenance tasks are async.

## 19. Open questions

1. Does the deployment terminate C-DAC traffic at an interceptor (#8.3), or does
   C-DAC post directly to Django? This decides only the ingress config, but it
   must be settled before the callback URL is registered with C-DAC.
2. Is one signature per transaction sufficient for orders that need multiple
   signatories, or do we need a sign-request aggregate now?
3. Should the signed PDF replace the entity's current document reference
   automatically, or does the calling module own that update? (This spec assumes
   the caller owns it and only returns `signed_file_id`.)
4. Is a consent/eKYC artefact required to be archived for legal audit beyond the
   signer certificate metadata we retain?
5. What is C-DAC's actual PKCS#7 blob size, so `PDF_SIGNATURE_CONTAINER_BYTES`
   ([`0016`](0016-pdf-services.md) #15) can be set with an adequate margin?
6. Should `ESignTransaction` rows be pruned or archived after a retention period,
   like the `MessageLog` question in 0009?

## 20. Implementation phases

1. **Domain skeleton** — `apps.esign`, model + migration + state machine, admin,
   constants, exceptions, provider ABC/registry, mock provider, unit tests.
2. **Module adapters** — `apps.pdf` and `apps.files` adapters against the agreed
   service functions, with fakes for tests. Blocked on
   [`0016`](0016-pdf-services.md) #14 and
   [`0014`](0014-file-storage-service.md) #6.1/#6.2 landing.
3. **APIs** — initiate, status, callback, retry; serializers, permissions,
   throttling, Swagger, envelope tests.
4. **CDAC addon** — keystore, request builder, XML signer, response parser and
   verifier, config, system checks, unit tests.
5. **Resilience** — expiry sweeper, `SIGNING` reconciliation, placeholder
   cleanup, retry, concurrency and duplicate-callback tests.
6. **Hardening and rollout** — security tests, production guards, docs/env
   updates, end-to-end run against the C-DAC test ESP.
