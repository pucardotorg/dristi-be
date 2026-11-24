# 0038 — DSC Token Signing with pyHanko, and Multi-provider eSign (`apps.esign` + `addon.dsc_esign`)

## Status

Proposed

## References

- [0000 — API Coding Specification](0000-api-coding-spec.md) — envelope, error-code, and layering rules
- [0014 — File Storage Service](0014-file-storage-service.md) — `apps.files`, owns document persistence and the `file_id` reference
- [0015 — eSign Module and CDAC eSign Addon](0015-cdac-esign.md) — `apps.esign` domain, provider interface, transaction lifecycle this spec extends
- [0016 — PDF Service](0016-pdf-services.md) — `apps.pdf`, owns signature-container preparation and PKCS#7 embedding
- [0017 — Orders / Payments](0017-orders-management.md) #9.3 — the provider registry and "resolve from the record, never from settings" rule this spec reuses
- [0034 — Public Configuration Store](0034-public-configuration-store.md) — where enabled signing methods are published to the UI
- `PRDs/signing-methods.md` — owner decisions: `SGM-02` (DSC), `SGM-05` (per-state `signingMethods`)
- POC: `dristi-solutions/pyhanko-bulksign` — proven local pyHanko DSC agent (Capricorn replacement), real-token verified

> **Scope note.** The domain (transaction lifecycle, state machine, prepare/embed
> orchestration, audit) already lives in `apps.esign` ([0015](0015-cdac-esign.md)).
> This spec adds two things. First, **multi-provider support** so C-DAC and DSC
> run **together** (an existing deployment keeps C-DAC; a state may enable DSC as
> well), modelled on the payments registry ([0017](0017-orders-management.md) #9.3).
> Second, **DSC token signing** as a second signing method, with a new
> **authenticated completion endpoint** for signatures produced on the client.
> Everything DSC-specific (local-agent contract, CMS assembly, certificate policy)
> lives in `addon.dsc_esign`; `apps.esign` stays provider-agnostic. PDF
> manipulation ([`apps.pdf`](0016-pdf-services.md)) and file persistence
> ([`apps.files`](0014-file-storage-service.md)) are reused in-process.

## Context

`PRDs/signing-methods.md` separates **digital signing** (umbrella: mobile OTP,
DSC, Aadhaar e-sign) from **e-sign** (Aadhaar only). `SGM-02` is **DSC**: the
signatory signs with their **own Digital Signature Certificate** — a physical USB
token and PIN — placing the signature on **every document** in a session. DSC is
a *sibling* of the C-DAC Aadhaar e-sign of [0015](0015-cdac-esign.md), switched on
per state via `signingMethods` (`SGM-05`), and **offered alongside** C-DAC, not
instead of it.

A working POC (`pyhanko-bulksign`) already signs court PDFs with a DSC token via
pyHanko and PKCS#11, replacing the proprietary Capricorn `pkiNetworkSign` agent
(real-token verified on HYP2003; also ePass2003 / WatchData ProxKey / SafeNet).

Consequences that shape the design:

- **C-DAC and DSC must coexist.** [0015](0015-cdac-esign.md) selects a single
  provider via `ESIGN_PROVIDER`. A global switch to DSC would break live C-DAC
  work: an in-flight C-DAC callback would be parsed by the DSC provider, C-DAC
  startup validation would turn off, and a C-DAC retry would create a DSC
  attempt. So the provider must be **per transaction**, resolved from the stored
  row after creation — exactly the payments rule ([0017](0017-orders-management.md)
  #9.3).
- **The DSC token is physical USB hardware on the signer's machine.** The server
  can never reach it, so — unlike C-DAC — the backend **cannot perform the
  signature**. Signing happens in a **local agent** on the signer's PC
  (`localhost`, the POC's `:1620`).
- **Two completion models therefore exist.** C-DAC completes by an **anonymous
  ESP callback** whose trust comes from a verified response signature. DSC
  completes by the **signer's own authenticated client** posting a signature.
  These are different trust models and must be kept apart at the endpoint level
  (#3, #8), or the anonymous callback becomes a way to complete a DSC transaction
  without authentication.
- **For DSC the signature comes from the client, so the server must verify it
  itself** against the document it prepared — C-DAC can trust the ESP response,
  but a client (buggy or compromised) can upload any CMS.

## Goals

- Add a **provider registry** to `apps.esign` so C-DAC and DSC are configured and
  run together, and every post-creation step resolves the provider from
  `transaction.provider`, never from settings.
- Add DSC as a second method reusing the `apps.esign` lifecycle, prepare/embed,
  storage, permissions, retry, and audit.
- Keep the anonymous ESP callback usable **only** by callback-completed providers,
  and add an **authenticated client-signature completion** endpoint usable **only**
  by client-signature providers — enforced by a provider capability, not a name.
- **Verify the client-supplied signature** against the prepared document before
  storing it, behind a provider hook so certificate policy stays in the addon.
- Publish the enabled methods to the UI and tell the browser, per initiation,
  whether to redirect to an ESP or call the local agent.
- Keep all token/key material on the signer's machine.

## Non-goals

- Re-specifying PDF ByteRange computation, container reservation, or PKCS#7
  embedding ([0016](0016-pdf-services.md) #14), or document storage
  ([0014](0014-file-storage-service.md)).
- The **local agent itself** (`pyhanko-bulksign`): packaging, driver bundling,
  token discovery, PIN handling, PKCS#11 sessions. This spec defines only the
  HTTP contract it must satisfy (#7) and its security obligations (#12).
- Batch signing / batch certificates (`SGM-04`).
- RFC-3161 TSA timestamps, PAdES-LTV, and verification of previously signed PDFs.
  (India CCA **trust-chain** policy is in scope only as a provider hook; the root
  set and its rollout are a follow-up — #18.)
- Server-side HSM/soft-certificate signing; any new broker.

---

## 1. Module placement and dependency direction

```text
src/
├── apps/
│   ├── esign/                         # 0015 + THIS SPEC
│   │   ├── providers/
│   │   │   ├── base.py                # provider ABC + Completion capability (extended)
│   │   │   └── registry.py            # get(name), names(), default — like apps.payments
│   │   └── services/
│   │       └── client_signature.py    # NEW — generic client-signature completion
│   ├── pdf/                           # 0016 — reused as-is
│   └── files/                         # 0014 — reused as-is
├── addon/
│   ├── cdac_esign/                    # 0015 — small change: is_active_provider → "is registered"
│   └── dsc_esign/                     # THIS SPEC — DSC provider, cert policy, agent contract
└── config/settings/base.py            # the only wiring point
```

```text
addon.dsc_esign   -- imports -->  apps.esign (provider base class, dataclasses, exceptions)
apps.esign        -- never imports --> addon.*          (and holds NO DSC-specific name)
apps.esign        -- imports -->  apps.pdf / apps.files *service functions only*
config.settings   -- references --> ESIGN_PROVIDERS = {"cdac": "...", "dsc": "..."}
```

The backend gains **no PKCS#11 dependency**: `python-pkcs11` and the vendor
modules live only in the local agent.

### 1.1 Layout

```text
src/addon/dsc_esign/
├── __init__.py
├── apps.py
├── provider.py          # DSCESignProvider(ESignProvider), completion=CLIENT_SIGNATURE
├── constants.py         # provider name, agent form keys, settings prefix
├── config.py            # resolve_config(): DSC_ESIGN_* settings, is_registered()
├── verify.py            # verify_client_signature(): digest, signature, certificate policy
├── checks.py            # startup validation when dsc is registered
└── tests/
    ├── test_provider.py
    ├── test_verify.py
    └── test_config.py
```

Nothing under `apps.esign` carries the string `"dsc"`; the module branches on the
provider's **capability**, not its name (#3, #8).

---

## 2. End-to-end flow

```text
Signer's browser            apps.esign (backend)                 Local DSC agent (:1620)        apps.pdf / apps.files
───────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 POST /esign/_esign           initiate_esign (0015 #2)
   {signing_method:"dsc"} ───▶ resolve provider = registry.get("dsc"); check method enabled (SGM-05)
                              check_can_sign; reject_if_in_progress
                              files.get_content(file_id) ──────────────────────────────────────▶ fetch source PDF
                              pdf.prepare_for_signing → (prepared, document_hash, field_name)
                              store_placeholder → placeholder_file_id
                              create ESignTransaction(PENDING, provider="dsc", document_hash)
                              provider.build_initiation
                                 → completion="CLIENT_SIGNATURE", agent_url, payload{digest,…}
     ◀── 201 {transaction_id, completion:"CLIENT_SIGNATURE", action_url, payload{digest,…}}
 POST {agent}/sign (digest) ───────────────────────────────────▶ PKCS#11: token signs the digest (PIN at START;
                                                                 per-request user confirmation, #12)
                                                                 → detached CMS (base64)
     ◀───────────── {status:"ok", pkcs7}
 POST /esign/transactions/{id}/_complete {pkcs7} ─▶ guard: provider.completion must be CLIENT_SIGNATURE
                              gate: lock, PENDING→SIGNING (0015 #8.2)
                              provider.verify_client_signature(txn, pkcs7)   ← digest + signature + cert policy (#8.1)
                              pdf.embed_signature(placeholder, pkcs7, field_name) → signed PDF
                              files.upload(signed) → signed_file_id ─────────────────────────────▶ store signed PDF
                              mark_success(signed_file_id)
     ◀── 200 {status:"SUCCESS", signed_file_id}
 GET /esign/transactions/{id} ──▶ status (idempotent source of truth)
```

C-DAC is unchanged: its initiation returns `completion:"CALLBACK"` with
`action_url` + `payload`, and completion stays the anonymous `/esign/_signed`
callback (#8.2).

---

## 3. Provider interface (`apps.esign.providers.base`)

The ABC gains an explicit **completion capability** so the two endpoints can
refuse the wrong kind of transaction **by capability, never by name**:

```python
class Completion(Flag):
    CALLBACK = auto()          # completes via the anonymous ESP callback (/esign/_signed)
    CLIENT_SIGNATURE = auto()  # completes via the authenticated _complete endpoint

class ESignProvider(ABC):
    name: ClassVar[str]
    completion: ClassVar[Completion]          # NEW

    def build_initiation(self, transaction, document_hash) -> ESignInitiation: ...
    def parse_response(self, payload) -> ESignProviderResponse: ...     # CALLBACK providers
    def verify_response(self, payload) -> None: ...                      # CALLBACK providers
    def verify_client_signature(self, transaction, pkcs7: bytes) -> ESignProviderResponse: ...  # CLIENT_SIGNATURE, NEW
```

- **C-DAC**: `completion = Completion.CALLBACK`. Unchanged.
- **DSC**: `completion = Completion.CLIENT_SIGNATURE`. Its `parse_response` and
  `verify_response` **raise** (`ESignCallbackMalformed` / `ESignResponseUntrusted`)
  — they are never valid for DSC, and must not be no-ops, because the anonymous
  callback's only trust gate is `verify_response`. A no-op there would let an
  anonymous `txn=dsc-<uuid>&signature=<any CMS>` form POST reach `_gate` →
  `_complete` and mark the row `SUCCESS`, bypassing authentication entirely.
- `verify_client_signature` is implemented only by CLIENT_SIGNATURE providers
  (default on the ABC raises `NotImplementedError`), and is where the addon's
  certificate policy lives (#8.1).

`ESignInitiation` gains a `completion` field (and renames the ESP-specific
`esign_url`/`form_fields` to a generic `action_url`/`payload`, keeping backward
compatibility for C-DAC). See #6.1.

---

## 4. Provider registry (`apps.esign.providers.registry`)

Modelled on `apps.payments.providers.registry` ([0017](0017-orders-management.md)
#9.3):

```python
get(name) -> ESignProvider          # by registered name, with name/path validation
names() -> list[str]                # every registered provider
get_default() -> ESignProvider|None # ESIGN_DEFAULT_PROVIDER (new C-DAC default)
```

Rules:

1. **`ESIGN_PROVIDERS`** maps name → dotted path, e.g.
   `{"cdac": "addon.cdac_esign.provider.CDACESignProvider", "dsc": "addon.dsc_esign.provider.DSCESignProvider"}`,
   plus **`ESIGN_DEFAULT_PROVIDER`**. The legacy **`ESIGN_PROVIDER`** stays a
   deprecated alias that is read into a one-entry registry when `ESIGN_PROVIDERS`
   is unset, so existing deployments keep working with no change.
2. `get(name)` validates, like payments, that the class subclasses
   `ESignProvider` and that its `name` matches the registry key.
3. **After a transaction exists, every step resolves the provider from
   `transaction.provider` via `get(transaction.provider)` — never from settings.**
   This applies to the callback gate, `_complete`, retry, and the reconciler.
   Changing configuration then never re-routes a transaction already in flight.
4. Initiation is the **only** place that chooses a provider, from the request's
   `signing_method` checked against the state's enabled `signingMethods`.

---

## 5. PDF Service and File Storage contracts consumed

Reused **unchanged** from [0015](0015-cdac-esign.md) #4.

- `prepare_for_signing(document, placeholder) -> (prepared_document, document_hash, field_name)`
  — reserves an empty `/Contents` container of `PDF_SIGNATURE_CONTAINER_BYTES` and
  returns the ByteRange digest. **`document_hash` is the digest the token signs.**
- `embed_signature(prepared_document, pkcs7, field_name) -> bytes`.
- `apps.files.upload / get_metadata / get_content` for placeholder, source, and
  signed documents, tagged as in [0015](0015-cdac-esign.md) #4.2.

The DSC CMS must be a **detached** SignedData (`ADOBE_PKCS7_DETACHED`) over the
ByteRange digest, with a digest algorithm equal to `PDF_SIGNATURE_HASH_ALGORITHM`,
and must fit `PDF_SIGNATURE_CONTAINER_BYTES`.

---

## 6. `ESignTransaction` model and APIs

No model schema change ([0015](0015-cdac-esign.md) #5): `provider`,
`provider_transaction_id`, `document_hash`, `signature_field_name`,
`placeholder_file_id`, `signed_file_id`, audit, retry, timestamps are all reused.
`(provider, provider_transaction_id)` stays the dedup key. State machine
unchanged: `PENDING → SIGNING → SUCCESS | FAILURE`, `PENDING → EXPIRED`.

All endpoints follow [0000](0000-api-coding-spec.md): DRF serializers, the `meta`
envelope, `error_responses()`, Swagger tag `esign`.

### 6.1 `POST /api/v1/esign/_esign` — initiate (extended)

**New request field** `signing_method` (string) selects the provider; it is
validated against the enabled `signingMethods` for the context (state), and
rejected with `ESIGN_METHOD_NOT_ENABLED` otherwise. When omitted it falls back to
`ESIGN_DEFAULT_PROVIDER` (C-DAC), so existing callers are unaffected.

**New response field** `completion` tells the browser what to do next, so the UI
does not hard-code provider behaviour:

| `completion` | Next step | Carried in |
| --- | --- | --- |
| `CALLBACK` (C-DAC) | **redirect**: POST `payload` to `action_url` (the ESP), then wait for the callback redirect. | `action_url`, `payload` |
| `CLIENT_SIGNATURE` (DSC) | **call the local agent**: POST `payload` to `action_url` (the agent), then POST the result to `_complete`. | `action_url`, `payload` |

`action_url`/`payload` are the renamed, provider-agnostic `esign_url`/`form_fields`
(old names kept as aliases for one release). For DSC, `payload` is
`{digest, hash_algorithm, field_name, transaction_id, page, cood, size}`.

**DSC response `201`**

```json
{
  "transaction_id": "7c9e2b10-0000-4000-8000-000000000001",
  "provider_transaction_id": "dsc-7c9e2b10-0000-4000-8000-000000000001",
  "completion": "CLIENT_SIGNATURE",
  "expires_at": "2026-11-23T15:45:00+05:30",
  "action_url": "http://localhost:1620/sign",
  "form_method": "POST",
  "payload": {
    "digest": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "hash_algorithm": "sha256",
    "field_name": "Signature1",
    "transaction_id": "7c9e2b10-0000-4000-8000-000000000001",
    "page": "1", "cood": "380,60", "size": "150,45"
  }
}
```

Errors: existing initiation codes ([0015](0015-cdac-esign.md) #6.1) plus
`ESIGN_METHOD_NOT_ENABLED` (new, #10).

### 6.2 `GET /api/v1/esign/transactions/{id}` — status (reused)

Unchanged ([0015](0015-cdac-esign.md) #6.2).

### 6.3 `POST /api/v1/esign/transactions/{id}/_complete` — client-signature completion (new)

Accepts a client-produced detached PKCS#7, **verifies it against the prepared
document** (#8.1), embeds it, stores the signed PDF, and marks `SUCCESS`. This is
the authenticated analogue of the anonymous C-DAC callback, and is the **only**
completion path for CLIENT_SIGNATURE providers.

- **Auth:** `IsAuthenticated` + `IsAuthenticatedAndRegistered`. The row is fetched
  with `get_object_or_404(filter(signer=request.user))`, so a transaction that is
  not the caller's returns **404** (consistent with the status/retry views).
- **Capability guard:** `get(transaction.provider).completion` must include
  `CLIENT_SIGNATURE`, else `409 ESIGN_TRANSACTION_NOT_PROCESSABLE`. The check is
  on the capability, not on the name `"dsc"`.
- **Body limit:** `pkcs7` is rejected before decoding if its base64 length exceeds
  `ESIGN_MAX_CLIENT_SIGNATURE_BYTES` (default sized to
  `PDF_SIGNATURE_CONTAINER_BYTES`), with the request body itself capped as the
  C-DAC callback already caps its body.
- **Idempotency:** the same `select_for_update` + gate as
  [0015](0015-cdac-esign.md) #8.2; a duplicate on a `SUCCESS` row returns the
  existing result; a `SIGNING` row held elsewhere returns `409`.

**Request** (`ClientSignatureCompleteSerializer`)

| Field | Type | Req | Description |
| --- | --- | --- | --- |
| `pkcs7` | string (base64) | yes | Detached CMS SignedData over `transaction.document_hash` for `signature_field_name`. Size-limited. |

The certificate metadata is **not** taken from the request; the server extracts
it from the verified CMS (#8.1), so a client cannot mislabel it.

**Response `200`** — the `ESignTransactionSerializer` body (same as status), with
`signed_file_id` populated.

Errors (#10): `400 ESIGN_CLIENT_SIGNATURE_MISSING | ESIGN_CLIENT_SIGNATURE_INVALID | ESIGN_CLIENT_SIGNATURE_MISMATCH`,
`403 ESIGN_CERTIFICATE_NOT_PERMITTED` (registered-DSC binding, #8.1),
`400 ESIGN_RESPONSE_STALE`, `404` (unknown / not the caller's),
`409 ESIGN_TRANSACTION_NOT_PROCESSABLE | ESIGN_ALREADY_IN_PROGRESS`,
`413` (body too large), `502 ESIGN_PDF_EMBED_FAILED | ESIGN_SIGNED_UPLOAD_FAILED`.

### 6.4 `POST /api/v1/esign/transactions/{id}/_retry` — retry (reused)

Unchanged behaviour, **made provider-correct**: the retry reuses
`get(transaction.provider)` (#4.3), so a C-DAC failure always retries as C-DAC and
a DSC failure as DSC, regardless of the current default.

### 6.5 `GET /api/v1/esign/methods` — enabled methods (new)

Lets the UI offer "Aadhaar OTP / My DSC" without hard-coding. Returns the methods
enabled for the context (state), derived from `signingMethods` (`SGM-05`):

```json
{ "methods": [ { "method": "cdac", "label": "Aadhaar OTP", "completion": "CALLBACK" },
               { "method": "dsc",  "label": "My DSC",      "completion": "CLIENT_SIGNATURE" } ] }
```

This may instead be delivered through the public configuration store
([0034](0034-public-configuration-store.md)); the shape above is the contract
either way.

---

## 7. Local-agent contract (`addon.dsc_esign` + `pyhanko-bulksign`)

The agent runs on the signer's machine, reached by the browser at `action_url`.
The backend never calls it.

### 7.1 `POST {action_url}` — sign a digest

**Request** — form-urlencoded or JSON, the `payload` from #6.1 (`digest`,
`hash_algorithm`, `field_name`, `transaction_id`).

**Response** — JSON: `{ "status": "ok", "pkcs7": "BASE64_DETACHED_CMS", "error": "" }`,
or `{ "status": "failed", "pkcs7": "", "error": "wrong PIN / token removed / …" }`.

Certificate/token errors surface here and are shown by the browser; the browser
then does **not** call `_complete`, leaving the row `PENDING` (it later `EXPIRED`s
or the user retries).

### 7.2 Required change to the POC agent, and the correct pyHanko call

The POC signs the **whole PDF** (`PdfSigner.sign_pdf`). For this integration the
agent must instead **sign the supplied digest** and return a **detached CMS**. The
correct pyHanko 0.38 call is **not** `async_sign_raw` — that hashes its input, so
passing the ByteRange digest would sign `H(digest)` and produce a bare signature
with no signed attributes, which no viewer can validate. Use:

```python
content_info = await signer.async_sign(
    data_digest=bytes.fromhex(digest),   # the ByteRange digest, already hashed
    digest_algorithm=hash_algorithm,     # "sha256", matches PDF_SIGNATURE_HASH_ALGORITHM
    use_pades=False,                      # ADOBE_PKCS7_DETACHED, matches prepare_for_signing
)
return base64.b64encode(content_info.dump()).decode("ascii")
```

`async_sign` returns an `asn1crypto.cms.ContentInfo` — a detached SignedData with
`contentType`, `messageDigest` and `signingTime` signed attributes — which is what
`embed_signature` expects and what `verify_client_signature` (#8.1) checks. Token
discovery, PIN, slot selection, locks and timeouts (`token_utils.py`) are reused
unchanged. The visible appearance is rendered **server-side** at preparation, so
the agent no longer stamps (confirm visual parity with the POC seal — #18).

This agent change is the single mandatory deviation from the POC and must be
coordinated with the `pyhanko-bulksign` maintainers (both Ubuntu and Windows).

---

## 8. Completion processing (`apps.esign.services.client_signature`)

Generic, provider-agnostic. It locks the row, gates it, calls the provider's
`verify_client_signature`, then shares the embed + store + success steps with the
C-DAC callback path.

### 8.1 Verify the client signature before trust

C-DAC trusts the ESP response because the response itself is verified. For DSC the
signature comes from the **client**, so `apps.esign` cannot trust it — it delegates
to `provider.verify_client_signature(transaction, pkcs7)`, which **must**, before
any embed, and raising the mapped error otherwise:

1. **Bind to the document.** Parse SignedData; require the `messageDigest` signed
   attribute to equal `bytes.fromhex(transaction.document_hash)`, and the CMS
   digest algorithm to equal `PDF_SIGNATURE_HASH_ALGORITHM`. Mismatch →
   `ESIGN_CLIENT_SIGNATURE_MISMATCH`. *(This is the gap the previous draft missed:
   `_reserved_region` checks the server's prepared PDF, and `_validated_pkcs7`
   checks only CMS structure; neither ties the signature to this document.)*
2. **Verify the signature.** Check the signer's signature over the signed
   attributes using the certificate embedded in the CMS (pyHanko validation with
   no trust roots; require `intact` and `valid`). Failure →
   `ESIGN_CLIENT_SIGNATURE_INVALID`.
3. **Check the certificate.** Validity period must include the signing time, and
   key usage must include `digitalSignature` / `nonRepudiation`. Certificate
   policy (India CCA chain, #18) lives here, in the addon.
4. **Bind to the signer (registered-DSC).** The certificate must match the
   signer's registered DSC identity; otherwise `ESIGN_CERTIFICATE_NOT_PERMITTED`.
   **Default: enforced** (open question #18 covers the identity source and any
   phased rollout).
5. **Audit.** Record the certificate **serial number, issuer, subject, and SHA-256
   fingerprint** in `response_audit` under keys `SENSITIVE_AUDIT_KEY` keeps
   (`certificate_subject`, `certificate_fingerprint`, `certificate_serial`,
   `certificate_issuer`). **Never store the certificate or the PKCS#7 blob.**

`verify_client_signature` returns an `ESignProviderResponse` so the shared
completion path treats both providers alike.

### 8.2 Idempotency and concurrency

Identical to [0015](0015-cdac-esign.md) #8.2: `select_for_update`, the
`PENDING → SIGNING` gate, embed + upload outside the lock, compare-and-set on
`SIGNING` before `mark_success`. The unique `(provider, provider_transaction_id)`
pair guarantees at most one `signed_file_id`.

### 8.3 Endpoint/provider separation

`process_callback` (the anonymous `/esign/_signed`) **refuses any transaction
whose provider is not `CALLBACK`**, and `_complete` refuses any that is not
`CLIENT_SIGNATURE`. Both checks are on the capability (#3). A test asserts an
anonymous `/esign/_signed` POST for a DSC transaction **never** changes its
status.

---

## 9. Failure, expiry, and recovery

Reused from [0015](0015-cdac-esign.md) #9, with the reconciler resolving the
provider from `transaction.provider` (#4.3). An abandoned DSC transaction stays
`PENDING` and is swept to `EXPIRED`; a row stuck in `SIGNING` is reconciled to
`FAILURE` with the placeholder retained for a retry.

---

## 10. Error codes

New codes are registered in `apps.esign.errors` with the `E03xxx` prefix; existing
codes keep their registered statuses. **The previous draft's claim of "no new
codes" and its 400-for-everything table were wrong.**

| Code | HTTP | New? | When |
| --- | --- | --- | --- |
| `ESIGN_METHOD_NOT_ENABLED` | 400 | **new** | `signing_method` not in the state's enabled methods. |
| `ESIGN_CLIENT_SIGNATURE_MISSING` | 400 | **new** | `pkcs7` absent/empty (client error, unlike the ESP-side `SIGNATURE_MISSING`=500). |
| `ESIGN_CLIENT_SIGNATURE_INVALID` | 400 | **new** | CMS not decodable, or signature does not verify. |
| `ESIGN_CLIENT_SIGNATURE_MISMATCH` | 400 | **new** | `messageDigest` ≠ `document_hash`, or wrong digest algorithm. |
| `ESIGN_CERTIFICATE_NOT_PERMITTED` | 403 | **new** | certificate fails policy / registered-DSC binding. |
| `ESIGN_TRANSACTION_NOT_PROCESSABLE` | 409 | reused | terminal row, or provider capability mismatch. |
| `ESIGN_RESPONSE_STALE` | 400 | reused | completion arrived past `expires_at + grace`. |
| `ESIGN_PDF_EMBED_FAILED` | 502 | reused | container too small / field missing. |
| `ESIGN_SIGNED_UPLOAD_FAILED` | 502 | reused | signed-PDF upload rejected/unavailable. |
| `ESIGN_ALREADY_IN_PROGRESS` | 409 | reused | a live transaction already covers the document. |
| `ESIGN_DISABLED` | 503 | reused | kill switch. |

The existing `SIGNATURE_MISSING` (E03018) and `SIGNATURE_INVALID` (E03019) stay
**500** and keep their ESP-callback meaning; DSC uses the new 400 client codes
instead. "Not your transaction" returns **404** via `get_object_or_404`, not 403.

---

## 11. Configuration

Multi-provider and DSC settings. DSC addon settings follow the **addon prefix
rule** (`DSC_ESIGN_*`), matching how `addon.cdac_esign` namespaces its own
settings; nothing DSC-specific is added under the generic `ESIGN_*` namespace.

| Setting | Owner | Meaning |
| --- | --- | --- |
| `ESIGN_PROVIDERS` | `apps.esign` | name → dotted path registry. |
| `ESIGN_DEFAULT_PROVIDER` | `apps.esign` | provider for initiations without `signing_method`. |
| `ESIGN_PROVIDER` | `apps.esign` | **deprecated** single-provider alias (maps to a one-entry registry). |
| `ESIGN_MAX_CLIENT_SIGNATURE_BYTES` | `apps.esign` | max accepted `pkcs7` size at `_complete`. |
| `SIGNING_METHODS` (per state, `SGM-05`) | `apps.esign` / [0034](0034-public-configuration-store.md) | methods enabled per state. |
| `DSC_ESIGN_AGENT_URL` | `addon.dsc_esign` | local agent sign URL returned as `action_url`. |
| `DSC_ESIGN_REQUIRE_REGISTERED_CERT` | `addon.dsc_esign` | enforce registered-DSC binding (#8.1.4); default `true`. |
| `DSC_ESIGN_TRUST_ROOTS` | `addon.dsc_esign` | CCA root set for certificate policy (#18). |

Reused unchanged: `ESIGN_ENABLED`, `ESIGN_TRANSACTION_TTL`,
`ESIGN_CALLBACK_GRACE_PERIOD`, `ESIGN_SIGNING_STUCK_TIMEOUT`,
`ESIGN_MAX_ATTEMPTS`, `PDF_SIGNATURE_CONTAINER_BYTES`,
`PDF_SIGNATURE_HASH_ALGORITHM`, `PDF_MAX_SIGN_INPUT_BYTES`.

### 11.1 Startup validation

- `apps.esign.checks` validates `ESIGN_PROVIDERS` (names resolve, classes are
  `ESignProvider`, names match) and that `ESIGN_DEFAULT_PROVIDER` is registered.
- **`addon.cdac_esign` change (explicit):** its `is_active_provider()` becomes
  **"is registered in `ESIGN_PROVIDERS`"**, and its `apps.esign.checks` E002/E004
  guards use the same rule, so enabling DSC alongside C-DAC does not silently turn
  off C-DAC's own startup validation.
- `addon.dsc_esign.checks` validates `DSC_ESIGN_AGENT_URL` and that
  `PDF_SIGNATURE_CONTAINER_BYTES` is large enough for a DSC CMS incl. the chain,
  when `dsc` is registered.

---

## 12. Security

- **No key material on the server.** The token and PIN never leave the signer's
  machine; the backend handles only the public digest and the detached CMS.
- **Endpoint/capability separation (#3, #8.3)** stops the anonymous callback from
  completing a DSC transaction.
- **Server-side signature verification (#8.1)** stops a buggy or compromised
  client from storing a CMS that does not actually sign this document, or from
  signing as another user (registered-DSC binding).
- **Local-agent "silent signing" (owned by `pyhanko-bulksign`, required here):**
  once the PIN is entered the agent can sign whatever the court site sends it.
  The agent **must** (a) restrict `CORS`/accepted origins to the court web
  origin(s) and bind `127.0.0.1`, and (b) require a **per-request human
  confirmation** (or a short, visible signing session the user starts and ends)
  so a malicious script on the court page cannot sign silently in the background.
  The spec records this as a hard requirement on the agent.
- **Upload size limit (#6.3)** on `pkcs7` and the request body.
- **Audit redaction** reused from [0015](0015-cdac-esign.md) #12: certificate
  metadata only (subject, issuer, serial, fingerprint), never the certificate or
  PKCS#7 blob; audit strings truncated.

---

## 13. Logging

Reused `EVENT_*` from [0015](0015-cdac-esign.md) #13. The client-signature
completion logs `SIGNATURE_EMBEDDED` / `SIGNED_STORED` / `ESIGN_SUCCEEDED` as the
C-DAC callback does, plus a verification event recording only the certificate
metadata and the verification outcome. No document bytes, digests, certificates,
or PKCS#7 content are logged.

---

## 14. Testing

- **Registry**: `get(name)` validation; `get(transaction.provider)` used by
  callback/complete/retry/reconciler; deprecated `ESIGN_PROVIDER` alias maps to a
  one-entry registry.
- **Capability separation**: an anonymous `/esign/_signed` POST for a DSC
  transaction never changes its status; `_complete` for a C-DAC transaction is
  refused; neither path compares the string `"dsc"`.
- **Signature verification** (`addon.dsc_esign.tests`): a CMS whose `messageDigest`
  ≠ `document_hash` → mismatch; a tampered signature → invalid; an expired cert or
  missing key usage → rejected; an unregistered cert → `CERTIFICATE_NOT_PERMITTED`;
  audit carries subject/issuer/serial/fingerprint, never the blob.
- **Correct pyHanko stand-in**: the backend integration test uses
  `SimpleSigner.async_sign(data_digest=bytes.fromhex(digest), digest_algorithm="sha256", use_pades=False)`
  as the token stand-in (not `async_sign_raw`), runs it through
  `prepare_for_signing → async_sign → verify_client_signature → embed_signature`,
  and validates the signed PDF carries one valid signature over the expected
  ByteRange.
- **API**: envelope + `meta`; auth; `signing_method` enabled/not-enabled;
  size-limit (413); error codes and their correct statuses; `GET /esign/methods`.
- **No regression**: C-DAC initiate/callback/retry unaffected when DSC is also
  registered.

---

## 15. Acceptance criteria

1. C-DAC and DSC are both registered; C-DAC initiate/callback/retry are unchanged.
2. `POST /esign/_esign {signing_method:"dsc"}` returns `completion:"CLIENT_SIGNATURE"`,
   `action_url`, and a digest-bearing `payload`; an unenabled method returns
   `ESIGN_METHOD_NOT_ENABLED`.
3. `POST /esign/transactions/{id}/_complete` verifies the CMS against the document
   (digest, signature, certificate, registered binding) before embedding; a CMS
   that does not match is rejected with the mapped 400/403, and nothing is stored.
4. An anonymous `/esign/_signed` POST can never complete a DSC transaction.
5. Retry and the reconciler always use `transaction.provider`.
6. The resulting PDF carries one valid signature over the expected ByteRange
   (software-signer integration test using `async_sign(data_digest=…)`).
7. Oversized `pkcs7` is rejected (413); audit holds certificate metadata only.
8. No token, PIN, or PKCS#11 dependency is added to the backend.

---

## 16. Design decisions

1. **Multi-provider from day one.** C-DAC and DSC coexist via a registry; the
   provider is resolved from the transaction after creation, so configuration
   never re-routes work in flight (payments rule, [0017](0017-orders-management.md)
   #9.3).
2. **Capability, not name.** The two completion endpoints branch on a provider
   `Completion` capability; `apps.esign` holds no `"dsc"` string.
3. **Verify the client signature.** Because DSC signatures arrive from the client,
   the server verifies digest + signature + certificate before storing, behind a
   provider hook so policy stays in the addon.
4. **Detached CMS over the server digest (confirmed — Option A)** via
   `async_sign(data_digest=…)`, not a whole signed PDF and not `async_sign_raw`.
5. **Synchronous; bulk = client loop** with one PIN entry per signing session.

---

## 17. Out of scope

Local-agent packaging/driver bundling; batch signing (`SGM-04`); RFC-3161 TSA,
PAdES-LTV, verification of previously signed PDFs; server-side HSM signing; any new
broker.

---

## 18. Open questions

1. **Registered-DSC identity source.** `verify_client_signature` binds the cert to
   the signer (#8.1.4); where is the signer's registered DSC identity held
   (certificate serial/fingerprint on the user record?), and is there a phased
   rollout where binding is audited before it is enforced?
2. **CCA trust roots.** Which India CCA root/intermediate set is loaded into
   `DSC_ESIGN_TRUST_ROOTS`, who maintains it, and is a missing chain a hard reject
   at `_complete` or a stored-and-warned state initially?
3. **Agent contract — RESOLVED: Option A (detached CMS).** The agent returns a
   detached CMS over the server-supplied digest; the whole-signed-PDF alternative
   is dropped. Feasible and lighter for the agent (a token natively signs a digest;
   pyHanko exposes it via `async_sign(data_digest=…, use_pades=False)`), and the
   backend reuses the proven C-DAC embed path. See §16.4.
4. **Signature appearance** — server-rendered stamp vs agent seal; confirm the
   y-axis origin against a real order PDF.
5. **`signingMethods` delivery** — a dedicated `GET /esign/methods` (#6.5) or the
   public configuration store ([0034](0034-public-configuration-store.md))?
6. **Agent per-request confirmation UX** (#12) across Ubuntu and Windows.

---

## 19. Implementation phases

1. **Provider registry + capability (`apps.esign`)** — `ESIGN_PROVIDERS`,
   `get(name)`, `Completion`, resolve-from-transaction in callback/retry/
   reconciler, deprecated `ESIGN_PROVIDER` alias, C-DAC `is_active_provider` →
   "is registered", startup checks, tests. *(No DSC yet; C-DAC behaviour
   unchanged.)*
2. **Client-signature completion (`apps.esign`)** — `client_signature` service,
   `verify_client_signature` hook, `_complete` endpoint with capability guard,
   size limit, serializers, Swagger, endpoint-separation tests.
3. **DSC provider (`addon.dsc_esign`)** — provider, `verify.py` (digest +
   signature + certificate policy + binding), config with `DSC_ESIGN_*`, checks,
   unit tests.
4. **Agent change** — coordinate the `pyhanko-bulksign` `async_sign(data_digest=…)`
   change (#7.2) on Ubuntu and Windows; backend integration test with a software
   signer stand-in; per-request confirmation.
5. **Methods surface + rollout** — `GET /esign/methods` / public config, UI
   wiring, security tests, end-to-end run against a real token; (follow-up) CCA
   trust roots, TSA.
