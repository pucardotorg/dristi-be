# eSign ↔ PDF Service integration: issues to raise

This lists the changes **outside `apps.pdf`** that are needed so the eSign
module ([spec 0015](../spec/0015-cdac-esign.md), branch
`feat/0015-cdac-esign`, not yet merged to `main`) works with the PDF Service
([spec 0016](../spec/0016-pdf-services.md), `apps.pdf`) and the File Storage
Service ([spec 0014](../spec/0014-file-storage-service.md), `apps.files`) as
they exist on `main`.

They were found by reviewing `origin/feat/0015-cdac-esign` against `main` +
`feat/0016-pdf-services`. Issues 1–3 were reproduced against the real
`apps.files` / `apps.pdf` code. Each section below is written so it can be
copied into a GitHub issue.

Changes already made on the `apps.pdf` side are listed at the end
([§ Done in apps.pdf](#done-in-appspdf-no-action-needed)).

| # | Title | Component | Severity |
| --- | --- | --- | --- |
| 1 | eSign uploads use `FileType` labels instead of values | `apps.esign` | Blocker |
| 2 | eSign system actor `"system"` is not a valid `File.user` | `apps.esign` (+ settings) | Blocker |
| 3 | Mock eSign provider returns a signature `embed_signature` rejects | `apps.esign` | High (local/dev flow) |
| 4 | Duplicate `PDF_*` signing settings in `base.py` and env files | config / `apps.esign` branch | Medium (merge conflict) |
| 5 | `PDF_MAX_SIGN_INPUT_BYTES` default differs (20 MiB vs `FILE_MAX_SIZE_BYTES`) | config | Low |
| 6 | Hash-algorithm check compares raw strings | `addon.cdac_esign` | Low |
| 7 | Drop the "PDF service not available" import fallback once both are merged | `apps.esign` | Low |
| 8 | End-to-end test with the real PDF Service | `apps.esign` tests | Medium |

---

## 1. eSign uploads use `FileType` labels instead of values

**Component:** `apps.esign` — `src/apps/esign/constants.py`

**Problem.** eSign passes `file_type` as the enum *label*:

```python
FILE_TYPE_PDF = "PDF"
FILE_TYPE_SIGNED_PDF = "DIGITALLY_SIGNED"
```

`apps.files.models.FileType` stores lowercase *values*
(`"pdf"`, `"digitally_signed"`), and `upload_file()` validates against
`FileType.values`. Both uploads fail:

```text
ValidationError: file_type must be one of ['pdf', 'document', 'image', 'signature', 'digitally_signed']
```

So placeholder storage at initiation (`ESIGN_FILE_STORAGE_UNAVAILABLE`) and
signed-PDF storage in the callback (`ESIGN_SIGNED_UPLOAD_FAILED`) both fail.
The eSign tests do not catch it because they use a fake file client.

**Fix.** Use the values:

```python
FILE_TYPE_PDF = "pdf"
FILE_TYPE_SIGNED_PDF = "digitally_signed"
```

(or `FileType.PDF` / `FileType.DIGITALLY_SIGNED` if importing the enum from
`apps.files.models` is acceptable). Update the fakes/tests that assert
`"PDF"` / `"DIGITALLY_SIGNED"`.

**Acceptance.** A test using the real `apps.files.services.upload_file` with
in-memory storage stores both artefacts.

---

## 2. eSign system actor `"system"` is not a valid `File.user`

**Component:** `apps.esign` — `conf.system_actor_id()`, `services/initiation.actor_id()`, settings `ESIGN_SYSTEM_ACTOR_ID`

**Problem.** When a transaction has no signer (the unauthenticated callback
leg), eSign uploads with `user_id = ESIGN_SYSTEM_ACTOR_ID`, default `"system"`.
`File.user` is a non-null FK to `users.User` (integer/UUID pk), and
`upload_file()` rejects it:

```text
ValidationError: No user with id 'system'.
```

Spec 0014 §10 / open question 3 says the system actor must be a **real user
row**, configured once as `FILE_SYSTEM_USER_ID`. `apps.pdf` (on this branch)
already reads `FILE_SYSTEM_USER_ID` and resolves it by email, `+91…` mobile
number or primary key (`apps.pdf.services.documents.resolve_system_user_id`).

**Fix (proposal).**

1. Drop `ESIGN_SYSTEM_ACTOR_ID`; use the shared `FILE_SYSTEM_USER_ID`
   (already in `config/settings/base.py`, `.env.example`, `.env.prod.example`,
   README on the PDF branch).
2. Resolve it to a user pk the same way `apps.pdf` does — ideally move that
   resolver into `apps.files.services` (e.g. `resolve_system_user_id()`) so
   both modules share one implementation (needs an `apps.files` change; raise
   separately if preferred).
3. Fail with a clear configuration error (and a system check) when it is
   unset or does not match a user.

**Acceptance.** Callback for a transaction with `signer=None` stores the
signed PDF attributed to the configured system user.

---

## 3. Mock eSign provider returns a signature `embed_signature` rejects

**Component:** `apps.esign` — `providers/mock.py`

**Problem.** The mock provider passes through whatever `signature` the test
client posts. With the real PDF Service, `embed_signature()` validates the
blob as a DER CMS `SignedData` and raises `PDFInvalidPKCS7` otherwise
(spec 0016 #14.2, `PDFInvalidPKCS7` is an `apps.pdf` addition). Any arbitrary
string therefore fails the local/dev flow with `ESIGN_PDF_EMBED_FAILED`.

**Fix (pick one).**

* Have the mock provider generate a real detached CMS signature over the
  `document_hash` with a throwaway self-signed key (e.g. pyHanko
  `signers.SimpleSigner` or `cryptography` PKCS7 builder) when the callback
  posts `status=1` without a signature, so local runs produce a PDF that
  opens with a (untrusted) signature panel; **or**
* document that local testers must post a base64 DER PKCS#7 in the
  `signature` field (the PDF service's `apps/pdf/tests/test_signing.py`
  shows how to build one).

The first option is recommended: it also enables issue 8.

---

## 4. Duplicate `PDF_*` signing settings in `base.py` and env files

**Component:** config (`config/settings/base.py`, `.env.example`, `.env.prod.example`, `README.md`) on the eSign branch

**Problem.** The eSign branch declares, under a "PDF Service (spec 0016)"
block in `base.py`:

```python
PDF_SIGNATURE_HASH_ALGORITHM = env("PDF_SIGNATURE_HASH_ALGORITHM", default="SHA256")
PDF_SIGNATURE_CONTAINER_BYTES = env.int("PDF_SIGNATURE_CONTAINER_BYTES", default=16384)
PDF_MAX_SIGN_INPUT_BYTES = env.int("PDF_MAX_SIGN_INPUT_BYTES", default=20971520)
```

and the same three variables in `.env.example`, `.env.prod.example` and the
README. The PDF branch already owns all `PDF_*` settings in its own block.
Merging both will conflict or define the settings twice.

**Fix.** When rebasing the eSign branch on `main` (after the PDF branch is
merged), delete that block and the duplicate env/README rows, and rely on the
PDF Service's block. eSign continues to read them with `getattr(settings, …)`.

---

## 5. `PDF_MAX_SIGN_INPUT_BYTES` default differs

**Component:** config

**Problem.** eSign defaults it to `20971520` (20 MiB); the PDF Service defaults
it to `FILE_MAX_SIZE_BYTES` (10 MiB). eSign reads the source through
`get_file_content()`, which is itself capped by `FILE_MAX_READ_BYTES`
(10 MiB default), and stores the prepared PDF through `upload_file()`, capped
by `FILE_MAX_SIZE_BYTES`. A 20 MiB limit is unreachable in practice, and a
source close to 10 MiB yields a prepared PDF (+ ~32 KiB container + overhead)
that `upload_file()` rejects.

**Fix.** Keep one default (the PDF Service's) and document that
`FILE_MAX_SIZE_BYTES` / `FILE_MAX_READ_BYTES` must exceed
`PDF_MAX_SIGN_INPUT_BYTES + 2 × PDF_SIGNATURE_CONTAINER_BYTES + 64 KiB` so the
prepared document can be stored and read back. Optionally add that as a
system check in `apps.esign`.

---

## 6. Hash-algorithm check compares raw strings

**Component:** `addon.cdac_esign` — `checks._check_hash_algorithm`

**Problem.** The check does
`config.hash_algorithm != str(settings.PDF_SIGNATURE_HASH_ALGORITHM).upper()`.
The PDF Service accepts `SHA256`, `SHA-256`, `sha256` (it normalises by
upper-casing and removing `-`). `SHA-256` vs `SHA256` would be flagged as a
mismatch although both produce the same digest.

**Fix.** Normalise both sides the same way (`upper().replace("-", "")`), or
compare against `apps.pdf.services.signing.hash_algorithm()` lazily.
Also restrict `CDAC_ESIGN_HASH_ALGORITHM` to `SHA256` (the only value
C-DAC eSign 2.1 accepts); the PDF Service allows SHA384/SHA512 for other
consumers.

---

## 7. Drop the import fallback for the PDF Service

**Component:** `apps.esign` — `clients/pdf.py`

**Problem.** `PDFClient._signing_module()` imports
`apps.pdf.services.signing` lazily and maps `ImportError` to
"The PDF service is not available.". This was needed while `apps.pdf` did not
exist. Once both are on `main`, a missing module is a deployment error that
should surface at startup, not as a per-request 502.

**Fix.** Import `apps.pdf.services.signing` normally (or add a system check
that it imports) and remove the stub-module patching in tests in favour of
issue 8. Note the adapter's `PREPARED_DOCUMENT_OVERHEAD_BYTES = 65536` must
stay in sync with `apps.pdf.services.signing.PREPARED_OVERHEAD_BYTES`; better,
import `prepared_document_max_bytes()` from `apps.pdf.services.signing`
instead of duplicating the formula.

---

## 8. End-to-end test with the real PDF Service

**Component:** `apps.esign` tests

**Problem.** eSign tests use a fake PDF client and a fake file client, which
is how issues 1–3 slipped through.

**Fix.** Add one integration test (in `apps/esign/tests/`) that uses the real
`apps.pdf.services.signing` and real `apps.files.services` with
`InMemoryStorage`:

1. upload a small PDF via `upload_file`,
2. `POST /api/v1/esign/_esign` (mock provider),
3. sign the returned `document_hash` with a throwaway key (or rely on the mock
   provider from issue 3) and `POST` the callback,
4. assert `SUCCESS`, a `digitally_signed` file exists, and the signed PDF
   validates with pyHanko (`validate_pdf_signature`, `intact` and `valid`) and
   still starts with the source bytes (incremental update).

---

## Done in `apps.pdf` (no action needed)

These came out of the same review and are already implemented on
`feat/0016-pdf-services`:

* **Embed size limit.** `embed_signature()` previously applied
  `PDF_MAX_SIGN_INPUT_BYTES` to the *prepared* document, so a source exactly
  at the limit could be prepared but not embedded (after the signer had
  already completed the OTP flow). It now allows
  `PDF_MAX_SIGN_INPUT_BYTES + 2 × PDF_SIGNATURE_CONTAINER_BYTES + 65536`,
  matching the eSign adapter's `prepared_document_max_bytes()`
  (`apps.pdf.services.signing.prepared_document_max_bytes()`).
* **API contract confirmed compatible** with the eSign adapter:
  `prepare_for_signing(document, placeholder)` returns an object with
  `prepared_document`, lowercase-hex `document_hash` and `field_name`;
  `embed_signature(prepared_document, pkcs7, field_name)` returns bytes;
  placeholder keys are exactly `page, x, y, width, height, reason, location,
  signer_name` (= `apps.esign.constants.PDF_PLACEHOLDER_KEYS`); error class
  names `PDFPageOutOfRange` / `PDFInvalidPlaceholder` (which the adapter maps
  to `ESIGN_INVALID_PLACEHOLDER`) match spec 0016 #14.3.
* **Settings names** `PDF_SIGNATURE_HASH_ALGORITHM`,
  `PDF_SIGNATURE_CONTAINER_BYTES`, `PDF_MAX_SIGN_INPUT_BYTES` match what the
  eSign checks and adapter read.
