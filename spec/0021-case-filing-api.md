# Case Filing API — Entry Points and Draft Management

## Status
Proposed

## 1. Goal

Provide REST endpoints for the complete case filing journey, from draft creation through participant management to submission, such that:

- Users can join existing registered cases or start new filings.
- **Draft initialization is lightweight** — clicking "start filing" creates only a session ID in cache, not database entries.
- **Lazy case creation** — the `cases` table and type-specific detail table are created atomically with the first substantive data entry (document upload, participant addition, evidence entry, or case details), not when the user clicks "start filing."
- Documents, participants, evidence, and case details can be managed independently across multiple sessions.
- The preview assembles the complete filing without revealing stale cached data.
- Validation gates submission and clearly reports what is incomplete.
- New case types reuse the same endpoints without code changes, only configuration.

This spec builds on:
- **0000**: API coding standards (error responses, pagination, filtering)
- **0005**: User model and authentication
- **0014**: File storage service for document uploads
- **0019**: Person, case filing, and evidence schema
- **0011**: Case workflows (for status transitions beyond draft)

## 2. Entry Points: Join vs. File

After login, the client offers two paths: **Join a case** and **File a case**.

### 2.1 Join a Case

The user provides a case number to join an existing, already-registered case as a participant.

```
GET /cases/by-number/{case_number}
```
PLEASE NOTE: This "case number" 

**Path Parameters:**
- `case_number` (string): The court-assigned case number (e.g., `CC/123/2024`)

**Response (200 OK):**
```json
{
  "case_id": "550e8400-e29b-41d4-a716-446655440000",
  "case_number": "CC/123/2024",
  "case_type": "CHEQUE_BOUNCE",
  "status": "REGISTERED",
  "filed_at": "2024-03-15T10:30:00Z",
  "court_id": "COURT_001"
}
```

**Error Responses:**
- `404 Not Found`: Case number does not exist, or case is not yet registered (drafts and cases under scrutiny are not joinable).

**Business Rules:**
- Only looks up `cases.case_number`, which is assigned at registration (spec 0017 §7.2).
- Cases with `status IN ('DRAFT_IN_PROGRESS', 'PENDING_SIGN', 'PENDING_PAYMENT', 'UNDER_SCRUTINY')` return 404.
- The endpoint returns only metadata; the user becomes a participant via subsequent calls to party endpoints.

### 2.2 File a Case

Shows the user's earlier filings and lets them create a new draft.

```
GET  /cases?status=DRAFT_IN_PROGRESS,PENDING_SIGN&created_by=me
POST /cases
```

**GET /cases (List User's Filings):**

Query Parameters:
- `status` (comma-separated): Filter by case status
- `created_by=me`: Show only cases I created
- `page`: Page number (spec 0000 §11). The project's default page-number
  pagination applies: 20 items per page, not configurable per request.

**Response (200 OK):**
```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "case_id": "uuid",
      "case_type": "CHEQUE_BOUNCE",
      "filing_number": "FIL/2024/001234",
      "case_number": null,
      "cnr_number": null,
      "status": "DRAFT_IN_PROGRESS",
      "court_id": "uuid",
      "filed_at": null,
      "registered_at": null,
      "created_at": "2024-03-10T14:22:00Z",
      "updated_at": "2024-03-12T09:15:00Z"
    }
  ],
  "meta": {
    "timestamp": "2024-03-12T14:45:00.000000+05:30",
    "app_version": "abc123def",
    "spec_version": "1.0"
  }
}
```

`count` is the total across pages; `next` and `previous` are the URLs of the
neighbouring pages (with the same filters), or `null`. `meta` is the standard
response envelope (spec 0000 §8), not pagination data.

**Note:**
This endpoint lists only cases that have been created in the database (i.e., have at least one saved data entry). Draft sessions (created via `POST /cases` but not yet populated with data) are not included in this listing because they exist only in cache, not in the `cases` table.

**POST /cases (Initialize Client-Side Draft):**

Initializes a client-side draft session without creating database entries. Database entries are created only when the user saves their first piece of actual information.

**Request Body:**
```json
{
  "case_type": "CHEQUE_BOUNCE",
  "court_id": "uuid-of-court-organization"
}
```

`court_id` is optional: the id of the court (an `Organization`) the case is to
be filed in. An unknown or inactive id is a 400.

**Response (201 Created):**
```json
{
  "draft_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "case_type": "CHEQUE_BOUNCE",
  "court_id": "uuid-of-court-organization",
  "created_at": "2024-03-15T10:30:00Z"
}
```

**Implementation:**
1. Generate a `draft_session_id` (UUID) on the server
2. Store minimal session info in Redis/cache with TTL (e.g., 24 hours):
   ```json
   {
     "draft_session_id": "uuid",
     "case_type": "CHEQUE_BOUNCE",
     "court_id": "uuid or null",
     "created_by": "user_id",
     "created_at": "timestamp"
   }
   ```
   When the first save creates the case, `court_id` from the draft is set on it.
3. Return `draft_session_id` to client

**No database entries created yet:**
The `cases` table and type-specific detail table (e.g., `cheque_bounce_case`) are NOT created at this point. They are created atomically when the user saves their first piece of information (document upload, participant addition, evidence entry, or case details).

**Why lazy creation:**
Users may click "start filing" and then abandon the process, or may take time to gather information. Creating database entries immediately would leave orphaned draft records. By deferring creation until the first meaningful action, we:
- Reduce database clutter from abandoned drafts
- Ensure every draft in the database has at least one piece of substantive data
- Maintain atomicity between case creation and the first data entry

**Subsequent calls:**
Once a case is created (after the first data entry), all subsequent endpoints use the `case_id` directly. Clients should:
- Store the returned `case_id` from the first successful data-entry call
- Use `case_id` for all subsequent operations on that filing
- The `draft_session_id` becomes obsolete once a `case_id` is obtained

**Error Responses:**
- `400 Bad Request`: Unknown `case_type`

## 3. Step 1: Document Upload

Every upload requires a case ID and a `document_type`. Only **case-level documents** use these endpoints. Vakalatnamas and POA documents are uploaded here too, as case documents (§3.4).

### 3.1 Upload Document

```
POST /cases/{case_id_or_draft_session_id}/documents
```

**Request (multipart/form-data):**
- `file`: The uploaded file (PDF, image)
- `document_type`: One of the enum values (see §3.4)

**Response (201 Created):**
```json
{
  "case_id": "uuid",
  "case_document_id": "uuid",
  "document_id": "uuid",
  "document_type": "BOUNCED_CHEQUE",
  "file_name": "cheque_scan.pdf",
  "file_size": 245678,
  "created_at": "2024-03-15T11:00:00Z"
}
```

**Transaction Steps:**
1. **Check if case exists:**
   - If path parameter is a valid `case_id` (exists in `cases` table), proceed with existing case
   - If path parameter is a `draft_session_id` (exists in cache/Redis), create the case first:
     a. Retrieve draft session metadata from cache
     b. **Atomically create case and type-specific table:**
        - Insert into `cases`:
          - `case_type` from draft session
          - `status = 'DRAFT_IN_PROGRESS'`
          - `created_by` from draft session
          - `filed_at = NULL`, `filing_number = NULL`
        - Insert into type-detail table (e.g., `cheque_bounce_case` with `case_id` matching the cases row, all JSONB columns defaulting to `{}`)
     c. Delete draft session from cache (case ID replaces it)

2. Upload file to storage service (spec 0014), get back `document_id`.
3. Insert `case_document` row with `(case_id, document_id, document_type, is_active=true)`.
4. Clear case preview cache (§6.2).

**Why case creation happens here:**
If document upload is the first action, the case must exist before we can link the document to it. This ensures atomicity: document upload → case creation → document linking all succeed or all fail together.

**Error Responses:**
- `400 Bad Request`: Unknown `document_type`, or the file fails the shared `apps.files` check: it must be a PDF, JPEG or PNG whose content matches its type (leading bytes), with a matching extension, within the size limit. The declared content type and the file name are only hints, so a renamed or mislabelled file is refused.
- `409 Conflict` (`E07001`): the case has been submitted (§7)
- `404 Not Found`: Neither case nor draft session exists for the provided ID
- `413 Payload Too Large`: File exceeds size limit

### 3.2 List Documents

```
GET /cases/{case_id}/documents?document_type={type}
```

**Query Parameters:**
- `document_type` (optional): Filter by type

**Response (200 OK):**
```json
{
  "results": [
    {
      "case_document_id": "uuid",
      "document_id": "uuid",
      "document_type": "BOUNCED_CHEQUE",
      "file_name": "cheque_scan.pdf",
      "file_url": "https://storage.example.com/...",
      "created_at": "2024-03-15T11:00:00Z"
    }
  ]
}
```

Used for in-step previews and completeness checks.

### 3.3 Delete Document

```
DELETE /case-documents/{case_document_id}
```

**Response (204 No Content)**

The document is addressed by its own id, which is unique across cases; the
owning case is found through it. A document on a case the caller did not
create returns 404.

**Implementation:**
Soft delete: sets `is_active = false`. The underlying `document` row is not deleted (spec 0017 §8.4). Evidence linked to the document is unlinked (`case_document_id` set to null) in the same transaction, so no evidence points at a document that is no longer part of the case.

### 3.4 Document Type Enum

The `document_type` must be one of:

**For cheque bounce cases:**
- `BOUNCED_CHEQUE`
- `RETURN_MEMO`
- `LEGAL_DEMAND_NOTICE`
- `PROOF_OF_DISPATCH`
- `PROOF_OF_DELIVERY_OF_DEMAND_NOTICE`
- `REPLY_TO_DEMAND_NOTICE`
- `PROOF_OF_DEBT`
- `AFFIDAVIT`
- `VAKALATNAMA`
- `POA_DOCUMENT`
- `OTHER_SUPPORTING_DOCUMENT`

**`VAKALATNAMA` and `POA_DOCUMENT`:** uploaded here, as case documents. The
advocate (§4.4) and POA holder (§4.5) endpoints do not take a document: the
filing UI collects signed documents only when the full set of case documents is
downloaded and uploaded back, so there is no step at which a vakalatnama or POA
document can be tied to one representation or mandate. They stay linked to the
case only until documents can be matched to them (for example by OCR); spec 0020
§5.3 and §6.3.

Each case type lists the document types it accepts, in the case type registry,
and `GET /case-types/{case_type}` serves that list. A known type the case type
does not accept is a 400. New case types extend this enum without changing the
endpoint.

## 4. Step 2: Party Management

Complainants, accused, witnesses and POA holders are all rows in `case_participant` (spec 0020 §4), differing by `role`; witnesses also have a `witness` row (spec 0020 §4.5). Advocates are `representation` rows (spec 0020 §6) and POA authority is `poa_mandate` rows (spec 0020 §5).

Adding a party uses a **per-role endpoint** under the case, for frontend clarity (see §9.2). Like documents and evidence, the case id in the path may be a draft session id: adding the first party creates the case (§9.1). Once something exists it is changed by its own id, which is unique across cases, so item endpoints are flat:

```
POST   /cases/{case_id_or_draft_session_id}/complainants
POST   /cases/{case_id_or_draft_session_id}/accused
POST   /cases/{case_id_or_draft_session_id}/witnesses
POST   /cases/{case_id_or_draft_session_id}/advocates
POST   /cases/{case_id_or_draft_session_id}/poa-holders

GET    /cases/{case_id}/participants?role={role}
GET    /cases/{case_id}/representations
GET    /cases/{case_id}/poa-mandates

PATCH  /case-participants/{case_participant_id}
DELETE /case-participants/{case_participant_id}
DELETE /representations/{representation_id}
PATCH  /poa-mandates/{poa_mandate_id}
DELETE /poa-mandates/{poa_mandate_id}
```

**Rules for every party write:**
- Only the filer (the case's `created_by`) can add, change or remove parties; other users' cases and items return 404.
- Writes are refused with `409 Conflict` (`E07001`) once the case has left `DRAFT_IN_PROGRESS` (§7).
- All rows a write creates or changes (person, institution, address, participant, witness, mandate, representation) are saved in one transaction: all of them, or none.
- Every successful write sets the case's `updated_at` and `updated_by`.
- Responses never include `created_by` / `updated_by`, nor the stored details of a reused institution (spec 0020 §3.4).
- List endpoints use the project's default page-number pagination (spec 0000 §11).

### 4.1 Complainants

```
POST /cases/{case_id_or_draft_session_id}/complainants
```

**POST Request Body (an individual):**
```json
{
  "person": {
    "name": "Rajesh Kumar",
    "phone_number": "+919876543210",
    "email_address": "rajesh@example.com",
    "date_of_birth": "1985-06-15",
    "age": null,
    "gender": "MALE",
    "relation": "SON_OF",
    "relative_name": "Ram Kumar"
  },
  "address": {
    "line1": "123 MG Road",
    "city": "Bengaluru",
    "pincode": "560001",
    "district": "Bengaluru Urban",
    "state": "Karnataka",
    "police_station": "Cubbon Park"
  },
  "is_party_in_person": false,
  "additional_details": {}
}
```

**POST Request Body (the filer, adding themselves):**
```json
{
  "self": true,
  "address": { ... }
}
```

**POST Request Body (an institution, acting through a person):**
```json
{
  "institution": {
    "entity_type": "PRIVATE_LIMITED_COMPANY",
    "entity_name": "ABC Pvt Ltd",
    "pan": "AAACA1234A",
    "cin": "U72200KA2010PTC052651",
    "contact_number": "080-22334455",
    "email_address": "legal@abc.example"
  },
  "person": { "name": "Priya Sharma", ... },
  "designation": "Director",
  "address": { ... }
}
```

Exactly one of `person` or `self` describes the individual, and either may be left out when `institution` is given. `designation` is required whenever both an individual and an institution are given. `date_of_birth` and `age` are both optional.

**Response (201 Created):**
```json
{
  "case_participant_id": "uuid",
  "case_id": "uuid",
  "person_id": "uuid",
  "institution_id": null,
  "role": "COMPLAINANT",
  "ordinal": 1,
  "name_at_filing": "Rajesh Kumar",
  "phone_number_at_filing": "+919876543210",
  "gender_at_filing": "MALE",
  "age_at_filing": 39,
  "designation_at_filing": null,
  "address_id": "uuid",
  "is_party_in_person": false,
  "additional_details": {},
  "is_active": true,
  "created_at": "2024-03-15T12:00:00Z"
}
```

**Transaction Steps:**

1. **Resolve the case type and check the case is editable** (404 if the id is neither the filer's case nor their live draft; 409 if submitted), and validate the whole body, before anything is written.

2. **Get or create the case** (same as §3.1, step 1): an existing case is used as is; a draft session creates the case and its type-specific detail row.

3. **Resolve the person** (spec 0020 §2.5):
   - `"self": true`: the filer's own `person`, fetched by `user_id`, or created from their account (name, mobile number) at `VERIFIED` the first time. Its stored values are not changed by this request.
   - `person`: a new `person` at `ASSERTED`, with no attempt to match. When given together with an institution, it is created with `institution_id` and `designation` set.
   - The same person cannot be both complainant and accused, nor complainant twice, on one case.

4. **Resolve the institution**, when given (spec 0020 §3.4): an existing institution with the same `pan` or `cin` is linked; otherwise a new one is created, with the request's address as its registered office. A reused institution's stored details are not returned or changed.
   - A `pan` and a `cin` that belong to two different institutions are refused (400).
   - The same institution cannot be both complainant and accused, nor hold one role twice, on one case.

5. **Write the address** through the address service (spec 0020 §7): an identical address reuses its row. District and state are not looked up here; the client pre-fills them from `GET /pincodes/{pincode}`. A newly created person also gets this address as their `correspondence_address`; an existing person's addresses are unchanged. The address is required for complainants. When the filer adds themselves without an address, it will come from their profile once profiles carry one; until then it must be sent.

6. **Create the participant:**
   - `role = 'COMPLAINANT'`, the next free `ordinal` for this role on this case
   - snapshot: `name_at_filing` (the person's name, or the institution's when there is no person), `phone_number_at_filing`, `gender_at_filing`, `age_at_filing` (from the date of birth when known, else the stated age), `designation_at_filing`
   - `address_id` from step 5, `start_date = now()`

7. **Touch the case** (`updated_at`), and clear the preview cache.

**PATCH `/case-participants/{case_participant_id}`:**
Updates only the participant's own data. The `person` and `institution` rows are **never** changed by it (spec 0020 §2.5). Any of these may be sent:

```json
{
  "name_at_filing": "Rajesh S. Kumar",
  "phone_number_at_filing": "+919876543210",
  "gender_at_filing": "MALE",
  "age_at_filing": 40,
  "designation_at_filing": "Managing Director",
  "address": { "line1": "456 New Street", "city": "Bengaluru", "pincode": "560002", "district": "...", "state": "...", "police_station": "..." },
  "is_party_in_person": true,
  "additional_details": {},
  "called_by_participant_id": "uuid",
  "what_will_witness_prove": "..."
}
```

- A changed address is written through the address service and `address_id` is repointed; the old address row is kept.
- `called_by_participant_id` and `what_will_witness_prove` apply only to witnesses (§4.3) and update the `witness` row.
- `role`, `person` and `institution` cannot be changed; remove the participant and add it again instead.
- Setting `is_party_in_person` to true is refused while the participant has an active advocate.
- `designation_at_filing` is accepted only for a person acting for an institution.

**DELETE `/case-participants/{case_participant_id}`:**
Soft delete: sets `is_active = false`, `end_date = now()`. Then, in the same transaction:
- the remaining active participants of that role are **renumbered** 1…n, so ordinals stay gap-free (spec 0020 §4.4);
- the participant's active representations end (`is_active = false`, `to_date = now()`), and so do the mandates in which they are the represented party; removing a POA holder revokes all their mandates;
- a POA holder left with no active mandate is removed too.

Refused (400) while an active witness names the participant as its caller: remove or re-point the witness first.

### 4.2 Accused

```
POST /cases/{case_id_or_draft_session_id}/accused
```

Same contract as complainants (§4.1), but `role = 'ACCUSED'`.

**Key Differences:**
1. `"self": true` is not accepted: a filer cannot name themselves as accused.
2. The accused is always a **new** `person` at `ASSERTED`; they are named by the complainant, not self-identifying.
3. An institution may be accused, with or without a person acting for it, exactly as for a complainant.

### 4.3 Witnesses

```
POST /cases/{case_id_or_draft_session_id}/witnesses
```

**POST Request Body:**
```json
{
  "person": { ... },
  "address": { ... },
  "called_by_participant_id": "uuid-of-complainant-or-accused",
  "what_will_witness_prove": "Eyewitness to the transaction on 2024-01-15",
  "additional_details": {}
}
```

**Implementation:**
- Same steps as §4.1, with `role = 'WITNESS'`, plus a `witness` row (spec 0020 §4.5) holding `called_by_participant_id`, `what_will_witness_prove` and `additional_details`.
- `called_by_participant_id` is required and must be an active COMPLAINANT or ACCUSED on the same case.
- `what_will_witness_prove` is required.
- A witness is always an individual: `institution` is not accepted. `"self": true` is. `is_party_in_person` does not apply to a witness and is refused.
- The address is optional for witnesses.
- A complainant or accused may also be a witness. The same person may be a witness more than once on a case (a witness recalled by the other side is a new participant, spec 0020 §4.5.3), but not twice for the same caller while both are active.
- `additional_details` is stored on the `witness` row; the participant's own `additional_details` stays `{}`. On PATCH, a witness's `additional_details` likewise changes the `witness` row.

**Response (201 Created):** the participant, as in §4.1, with a `witness` block (`null` for every other role, here and in `GET /cases/{id}/participants`):
```json
{
  "case_participant_id": "uuid",
  "role": "WITNESS",
  ...
  "witness": {
    "called_by_participant_id": "uuid",
    "what_will_witness_prove": "Eyewitness to the transaction on 2024-01-15",
    "additional_details": {}
  }
}
```

### 4.4 Representation (Advocates)

```
POST   /cases/{case_id_or_draft_session_id}/advocates
DELETE /representations/{representation_id}
```

**POST Request Body:**
```json
{
  "advocate_id": "uuid",
  "client_participant_ids": ["uuid1", "uuid2", "uuid3"]
}
```

**Response (201 Created):**
```json
{
  "representation_ids": ["uuid1", "uuid2", "uuid3"],
  "advocate_id": "uuid"
}
```

**Validation** (spec 0020 §6), before anything is written:
- `advocate_id` is an `AdvocateProfile` with `approval_status = ACCEPTED`; PENDING and REJECTED advocates are refused.
- Each client is an active COMPLAINANT or ACCUSED on this case, is not marked `is_party_in_person`, and is not the advocate themselves (the advocate's user is not the client person's user).
- The advocate does not already actively represent that client. A client may have several advocates.

**Transaction Steps:**
1. Get or create the case (same as §3.1, step 1).
2. For each client, insert a `representation` row with `case_id`, `advocate_id`, `case_participant_id`, `is_active = true`, `from_date = now()`.
3. Return the created `representation_ids`.

**Why multiple rows:**
Three clients = three rows with the same `advocate_id` (spec 0020 §6.3).

**The vakalatnama:** uploaded as a case document of type `VAKALATNAMA` (§3), not with this request. The filing UI collects signed documents only when the full set of case documents is downloaded and uploaded back, so a vakalatnama cannot yet be tied to one representation (spec 0020 §6.3). With no document to change, a representation has no PATCH; changing the advocate or a client is DELETE then POST.

**DELETE:**
Sets `is_active = false`, `to_date = now()`. Rows are never hard-deleted.

### 4.5 Power of Attorney Holders

```
POST   /cases/{case_id_or_draft_session_id}/poa-holders
PATCH  /poa-mandates/{poa_mandate_id}
DELETE /poa-mandates/{poa_mandate_id}
```

**POST Request Body:**
```json
{
  "person": {
    "name": "Suresh Patel",
    "phone_number": "+919123456789",
    ...
  },
  "address": { ... },
  "represented_participant_ids": ["uuid1", "uuid2"],
  "poa_type": "Limited to this case only",
  "additional_details": {}
}
```
`"self": true` may replace `person` when the filer is the POA holder, including a filer who is already a complainant acting for a co-complainant: they get a separate POA_HOLDER participant.

**Response (201 Created):**
```json
{
  "case_participant_id": "uuid",
  "poa_mandate_ids": ["uuid1", "uuid2"],
  "person_id": "uuid",
  "role": "POA_HOLDER"
}
```

**Validation** (spec 0020 §5), before anything is written:
- Each represented participant is an active COMPLAINANT or ACCUSED on this case, and is not the holder's own person.
- A POA holder is always an individual: `institution` is not accepted. The address is required.

**Transaction Steps:**
1. Get or create the case (same as §3.1, step 1).
2. Resolve the person (§4.1, step 3): the filer's own with `self`, otherwise a new `person` at `ASSERTED`.
3. Write the address and create the `case_participant` with `role = 'POA_HOLDER'` (§4.1, steps 5–6).
4. For each represented participant, insert a `poa_mandate` row with `case_id`, `poa_participant_id`, `represented_participant_id`, `poa_type`, `is_active = true`, `granted_at = now()`.

**Why multiple mandate rows:**
One POA acting for 2 of 3 complainants = 2 `poa_mandate` rows pointing to the same `poa_participant_id`.

**The POA document:** uploaded as a case document of type `POA_DOCUMENT` (§3), not with this request, for the same reason as the vakalatnama (§4.4).

**PATCH:**
Updates `poa_type`.

**DELETE:**
Revokes the mandate: `is_active = false`, `revoked_at = now()`. Revoking a holder's last active mandate also removes the holder's participant row (§4.1 DELETE), since a POA holder with no one to act for is no longer a party.

## 5. Step 3: Case Details and Evidence

### 5.1 Evidence (Sections 1 & 2: Cheques, Notices)

```
POST   /cases/{case_id_or_draft_session_id}/evidence
GET    /cases/{case_id}/evidence?evidence_type={type}
PATCH  /case-evidence/{case_evidence_id}
DELETE /case-evidence/{case_evidence_id}
```

Adding and listing evidence happen under the case. Updating and removing one
piece of evidence use its own id, which is unique across cases; the owning case
is found through it, and evidence on a case the caller did not create returns
404.

On POST, `evidence_type` is sent in the request body only, never as a query
parameter. The `evidence_type` query parameter exists on GET, as a filter.

For cheque bounce, each cheque has one `RETURN_MEMO` and one
`LEGAL_DEMAND_NOTICE`, matched to it by `ordinal`: cheque #1, return memo #1,
demand notice #1.

**POST Request Body (Cheque):**
```json
{
  "evidence_type": "CHEQUE",
  "case_document_id": "uuid-of-uploaded-scan",
  "evidence_info": {
    "cheque_date": "2024-01-15",
    "amount": 50000,
    "cheque_number": "456789",
    "ifsc_code": "SBIN0001234",
    "bank_name": "State Bank of India",
    "bank_branch": "MG Road"
  }
}
```

**POST Request Body (Return Memo):**
```json
{
  "evidence_type": "RETURN_MEMO",
  "case_document_id": "uuid",
  "evidence_info": {
    "presentation_date": "2024-01-18",
    "return_date": "2024-01-22",
    "return_reason": "Funds insufficient"
  }
}
```

**POST Request Body (Demand Notice):**
```json
{
  "evidence_type": "LEGAL_DEMAND_NOTICE",
  "case_document_id": "uuid",
  "evidence_info": {
    "nature_of_debt": "Loan",
    "cheque_issue_reason": "Repayment of loan",
    "dispatch_date": "2024-02-01",
    "mode_of_service": "Registered post",
    "tracking_number": "RR123456789IN",
    "is_delivered": true,
    "delivery_date": "2024-02-05",
    "accused_replied": false,
    "payment_status": "No payment"
  }
}
```

**Response (201 Created):**
```json
{
  "case_evidence_id": "uuid",
  "case_id": "uuid",
  "evidence_type": "CHEQUE",
  "ordinal": 1,
  "evidence_info": { ... },
  "created_at": "2024-03-15T13:00:00Z"
}
```

**Transaction Steps:**
1. Resolve the case type from the `case_id` or the draft session (404 if neither belongs to the caller).

2. Validate before writing anything: the case type must accept `evidence_type`, and `evidence_info` must match its schema (§5.2). A failure is a 400 and creates no case.

3. **Get or create the case:**
   - If path parameter is a valid `case_id`, proceed with existing case
   - If path parameter is a `draft_session_id`, atomically create case and type-specific table (same as §4.1, step 1)

4. Assign next `ordinal` for `(case_id, evidence_type)`: one more than the highest active ordinal, with the case row locked so concurrent adds cannot take the same number.

5. Insert `case_evidence` row.

6. Clear preview cache.

**Why one endpoint for all evidence:**
New case types add new `evidence_type` values and their schemas, not new endpoints or tables. This replaces type-specific calls like `POST /cheque_bounce`.

**PATCH:**
Updates `evidence_info`, `case_document_id`, or both; at least one must be sent. `case_document_id` links a document uploaded after the evidence was entered (spec 0020 §11.4), and `null` unlinks it; leaving it out keeps the current link. The document must be an active document of the same case. Changing `evidence_type` is not allowed; delete and recreate instead.

**DELETE:**
Soft delete: sets `is_active = false`.

**GET:**
Lists evidence, optionally filtered by `evidence_type`.

### 5.2 Evidence Info Schemas

Each `evidence_type` has a required schema validated on POST/PATCH. The
schemas live in code, in the case type registry
(`apps/cases/services/case_types.py`), and are served to clients by
`GET /case-types/{case_type}` so forms are built from the same source the
server validates against.

All schemas are strict (`"additionalProperties": false`): an unknown key is a
400, so a typo is reported rather than silently stored. Required text fields
must be non-empty. Dates are `YYYY-MM-DD`. Every problem is reported at once,
under `evidence_info`.

**`CHEQUE`** (as written on the cheque leaf, plus the drawer's bank):
```json
{
  "type": "object",
  "required": ["cheque_date", "amount", "cheque_number", "ifsc_code", "bank_name", "bank_branch"],
  "properties": {
    "cheque_date": { "type": "string", "format": "date" },
    "amount": { "type": "number", "exclusiveMinimum": 0 },
    "cheque_number": { "type": "string", "pattern": "^[0-9]{6}$" },
    "ifsc_code": { "type": "string", "pattern": "^[A-Z]{4}0[A-Z0-9]{6}$" },
    "bank_name": { "type": "string", "minLength": 1 },
    "bank_branch": { "type": "string", "minLength": 1 }
  },
  "additionalProperties": false
}
```
`cheque_number` is the six-digit number, not the full MICR line.

**`RETURN_MEMO`** (from the memo the bank issued when the cheque was dishonoured):
```json
{
  "type": "object",
  "required": ["presentation_date", "return_date", "return_reason"],
  "properties": {
    "presentation_date": { "type": "string", "format": "date" },
    "return_date": { "type": "string", "format": "date" },
    "return_reason": { "type": "string", "minLength": 1 }
  },
  "additionalProperties": false
}
```

**`LEGAL_DEMAND_NOTICE`** (nature of debt, the statutory notice, and any payment against the cheque):
```json
{
  "type": "object",
  "required": [
    "nature_of_debt", "cheque_issue_reason", "dispatch_date",
    "mode_of_service", "is_delivered", "payment_status"
  ],
  "properties": {
    "nature_of_debt": { "type": "string", "minLength": 1 },
    "cheque_issue_reason": { "type": "string", "minLength": 1 },
    "dispatch_date": { "type": "string", "format": "date" },
    "mode_of_service": { "type": "string", "minLength": 1 },
    "tracking_number": { "type": "string", "minLength": 1 },
    "is_delivered": { "type": "boolean" },
    "delivery_date": { "type": "string", "format": "date" },
    "accused_replied": { "type": "boolean" },
    "payment_status": { "type": "string", "minLength": 1 }
  },
  "additionalProperties": false,
  "if": { "properties": { "is_delivered": { "const": true } }, "required": ["is_delivered"] },
  "then": { "required": ["delivery_date"] }
}
```
`delivery_date` is required when `is_delivered` is true; the 15-day payment
window runs from it.

**Not yet enforced:**
- `return_reason`, `nature_of_debt`, `cheque_issue_reason`, `mode_of_service`
  and `payment_status` are dropdowns in the UI but accept any non-empty text
  until their option lists are agreed; each then becomes an `enum`.
- Date ordering (presentation not before the cheque date, return not before
  presentation, delivery not before dispatch) cannot be expressed in JSON
  Schema, and the first rule spans two evidence rows.
- `amount` is a JSON number; a money-safe representation (integer paise or a
  decimal string) is an open question.

### 5.3 Case Details (Sections 3 & 4: Type-Specific JSON)

```
PUT /cases/{case_id_or_draft_session_id}/details/{section}
GET /cases/{case_id}/details
```

The request body is the whole section object; it replaces what was stored, it
is not merged with it.

**PUT Request Body (Section 3: Jurisdiction & Limitation):**
```json
{
  "cheque_deposited_by_payee": true,
  "payee_ifsc_code": "HDFC0000512",
  "payee_bank_name": "HDFC Bank",
  "payee_bank_branch": "Kochi",
  "bank_police_station": "Ernakulam Central",
  "other_complaints_pending": false,
  "cause_of_action_date": "2024-02-21"
}
```

**PUT Request Body (Section 4: ADR, Other Details & Prayer):**
```json
{
  "adr_preference": "MAYBE",
  "other_details": "",
  "interim_relief": "<p>Direct the Accused to pay interim compensation under Section 143A ...</p>",
  "final_relief": "<p>Take cognizance of the offence committed by the Accused under Section 138 ...</p>"
}
```

**Response (200 OK):**
```json
{
  "case_id": "uuid",
  "section": "jurisdiction_limitation",
  "data": { ... }
}
```

**Implementation:**
1. Resolve the case type from the `case_id` or the draft session (404 if neither belongs to the caller).

2. Validate before writing anything (a failure is a 400 and creates no case):
   - `{section}` must be one of the case type's sections. For `CHEQUE_BOUNCE`: `jurisdiction_limitation`, `adr_other_prayer`.
   - The body must match that section's schema (below). Errors are reported under `data`.

3. **Get or create the case:**
   - If path parameter is a valid `case_id`, proceed with existing case
   - If path parameter is a `draft_session_id`, atomically create case and type-specific table (same as §4.1, step 1)

4. Replace that JSONB column on the type-detail table (`cheque_bounce_case.jurisdiction_limitation`).

5. Clear preview cache.

**Section schemas (`CHEQUE_BOUNCE`):** like the evidence schemas, these live in
the case type registry, are served by `GET /case-types/{case_type}`, and are
strict (`"additionalProperties": false`).

`jurisdiction_limitation` (which court can hear the case, and whether the complaint is in time):
```json
{
  "type": "object",
  "required": ["cheque_deposited_by_payee", "cause_of_action_date"],
  "properties": {
    "cheque_deposited_by_payee": { "type": "boolean" },
    "payee_ifsc_code": { "type": "string", "pattern": "^[A-Z]{4}0[A-Z0-9]{6}$" },
    "payee_bank_name": { "type": "string", "minLength": 1 },
    "payee_bank_branch": { "type": "string", "minLength": 1 },
    "bank_police_station": { "type": "string", "minLength": 1 },
    "other_complaints_pending": { "type": "boolean" },
    "cause_of_action_date": { "type": "string", "format": "date" }
  },
  "additionalProperties": false,
  "if": { "properties": { "cheque_deposited_by_payee": { "const": true } }, "required": ["cheque_deposited_by_payee"] },
  "then": { "required": ["payee_ifsc_code", "payee_bank_name", "payee_bank_branch", "bank_police_station"] }
}
```
Jurisdiction follows the branch where the cheque was presented and the
complainant holds the account, so the payee's bank details and that branch's
police station are required when the payee deposited the cheque.
`other_complaints_pending` records whether another Section 138 complaint is
pending between the same parties. The complaint filing date is not part of the
section: it is the case's `filed_at`, set at submission.

`adr_other_prayer` (willingness to settle, other details for the court, and the relief sought):
```json
{
  "type": "object",
  "required": ["final_relief"],
  "properties": {
    "adr_preference": { "enum": ["YES", "NO", "MAYBE"] },
    "other_details": { "type": "string" },
    "interim_relief": { "type": "string" },
    "final_relief": { "type": "string", "minLength": 1 }
  },
  "additionalProperties": false
}
```
`other_details`, `interim_relief` and `final_relief` hold rich-text editor
output and are stored as sent; they must be sanitized wherever they are
rendered (preview, PDFs).

**Open questions:**
- `bank_police_station` is free text; if police stations become master data it
  should hold the station's id.
- Required fields are enforced on every save, so a section cannot be saved
  half-filled. If the client autosaves drafts, required fields may need to move
  to the completeness check (§6.3) instead.

**Why section-based:**
The endpoint doesn't mention "cheque bounce," so a second dispute type (e.g., civil suit) reuses the same endpoint with its own sections.

**GET /cases/{case_id}/details:**
Returns all sections for the case type:
```json
{
  "jurisdiction_limitation": { ... },
  "adr_other_prayer": { ... }
}
```

### 5.4 Promoted Columns: Open Design Question

Spec 0017 §9.4 notes that `cheque_bounce_case` currently has promoted columns:
- `bank_account_number`
- `cheque_number`
- `return_memo_date`
- `drawee_bank`

Since cheques are now `case_evidence` rows and a case can have multiple cheques, these columns would duplicate data from one of them.

**Options:**

**(a) Drop promoted columns:**
Remove them from `cheque_bounce_case`. Searches on amount/date index into `case_evidence.evidence_info`.

**(b) Keep as derived values:**
Maintain them as values from `CHEQUE` ordinal 1 (or earliest `return_memo_date` across all cheques). The service updates them whenever cheque evidence changes. The client never writes them directly.

**Recommendation:** Start with (a). Add indexes on `case_evidence`:
```sql
CREATE INDEX ON case_evidence ((evidence_info->>'amount')::numeric) WHERE evidence_type = 'CHEQUE';
CREATE INDEX ON case_evidence ((evidence_info->>'cheque_date')::date) WHERE evidence_type = 'CHEQUE';
```

Promote to columns (option b) only if query performance requires it.

## 6. Preview and Validation

### 6.1 Full Assembled Filing

```
GET /cases/{case_id}
```

**Response (200 OK):**
```json
{
  "case_id": "uuid",
  "case_type": "CHEQUE_BOUNCE",
  "filing_number": "FIL/2024/001234",
  "status": "DRAFT_IN_PROGRESS",
  "filed_at": null,
  "created_at": "2024-03-15T10:30:00Z",
  "updated_at": "2024-03-15T14:22:00Z",
  "participants": [
    {
      "case_participant_id": "uuid",
      "role": "COMPLAINANT",
      "ordinal": 1,
      "name_at_filing": "Rajesh Kumar",
      "phone_number_at_filing": "+919876543210",
      "address": {
        "line1": "123 MG Road",
        "city": "Bangalore",
        "pincode": "560001"
      },
      "is_party_in_person": false,
      "is_active": true
    }
  ],
  "representations": [
    {
      "representation_id": "uuid",
      "advocate_id": "uuid",
      "advocate_name": "Adv. Sharma",
      "client_participant_id": "uuid",
      "is_active": true
    }
  ],
  "poa_mandates": [
    {
      "poa_mandate_id": "uuid",
      "poa_participant_id": "uuid",
      "poa_holder_name": "Suresh Patel",
      "represented_participant_id": "uuid",
      "poa_type": "Limited to this case",
      "is_active": true
    }
  ],
  "evidence": [
    {
      "case_evidence_id": "uuid",
      "evidence_type": "CHEQUE",
      "ordinal": 1,
      "evidence_info": {
        "cheque_number": "456789",
        "amount": 50000.00,
        "cheque_date": "2024-01-15"
      }
    }
  ],
  "documents": [
    {
      "case_document_id": "uuid",
      "document_type": "BOUNCED_CHEQUE",
      "file_name": "cheque_scan.pdf",
      "file_url": "https://..."
    }
  ],
  "details": {
    "jurisdiction_limitation": { ... },
    "adr_other_prayer": { ... }
  }
}
```

**Data Sources:**
- `cases` and type-detail table joined
- Active `case_participant` rows (where `is_active = true`)
- Active `representation` and `poa_mandate` rows
- Active `case_evidence` rows
- Active `case_document` rows

**Participant data is frozen:**
`name_at_filing`, `phone_number_at_filing`, and `address_id` come from `case_participant`, **not** `person`. The preview shows the case as it was filed (spec 0017 §3.4).

### 6.2 Caching Strategy

The assembled result is cached under `case:{case_id}:preview` with a TTL (e.g., 1 hour).

**Cache Invalidation:**
Every write endpoint (POST/PATCH/DELETE on documents, participants, evidence, details) clears this cache entry. This ensures:
- The preview cannot be stale.
- Repeated opens don't re-query the database.

**Implementation:**
```python
from django.core.cache import cache

def clear_case_preview_cache(case_id):
    cache.delete(f"case:{case_id}:preview")
```

### 6.3 Completeness Validation

```
POST /cases/{case_id}/validate
```

**Response (200 OK when valid):**
```json
{
  "is_valid": true,
  "errors": []
}
```

**Response (200 OK when invalid):**
```json
{
  "is_valid": false,
  "errors": [
    {
      "field": "participants.complainants",
      "message": "At least one active complainant is required"
    },
    {
      "field": "evidence.cheque",
      "message": "At least one cheque evidence is required"
    },
    {
      "field": "documents.BOUNCED_CHEQUE",
      "message": "Document type BOUNCED_CHEQUE is required but not uploaded"
    },
    {
      "field": "representations",
      "message": "Complainant #1 has no advocate and is not marked as party-in-person"
    }
  ]
}
```

**Validation Checks:**

1. **Participants:**
   - At least one active complainant (`role = 'COMPLAINANT'`, `is_active = true`)
   - At least one active accused (`role = 'ACCUSED'`, `is_active = true`)

2. **Representation:**
   - Each complainant either:
     - Has an active `representation` row, OR
     - `is_party_in_person = true`
   - When the case has any active `representation`, it has at least one active `VAKALATNAMA` case document. Vakalatnamas are case documents, not linked to a representation (§3.4), so this is checked per case, not per advocate.

3. **POA Mandates:**
   - When the case has any active `poa_mandate`, it has at least one active `POA_DOCUMENT` case document (checked per case, for the same reason).

4. **Evidence (cheque bounce specific):**
   - At least one `CHEQUE` evidence row
   - Each cheque has required fields in `evidence_info` (validated against schema §5.2)

5. **Documents:**
   - Every required `document_type` from the checklist exists as an active `case_document`
   - Checklist for `CHEQUE_BOUNCE`:
     - `BOUNCED_CHEQUE`
     - `RETURN_MEMO`
     - `LEGAL_DEMAND_NOTICE`
     - `PROOF_OF_DISPATCH`

6. **Case Details:**
   - `jurisdiction_limitation` and `adr_other_prayer` JSONs pass their schemas (defined per case type)

**When to call:**
Client calls this before attempting to submit for signing. Invalid cases cannot advance to `PENDING_SIGN`.

## 7. Status Transitions

Draft creation sets `status = 'DRAFT_IN_PROGRESS'`. Moving through the lifecycle requires additional endpoints.

**Only drafts can be changed.** Every write (uploading or removing a document, adding, changing or removing evidence, saving a details section) is refused with `409 Conflict` and code `E07001` once the case has left `DRAFT_IN_PROGRESS`, so what the court reviews cannot change underneath it. Reads are unaffected. Every successful write also sets the case's `updated_at` (and `updated_by`), which listings show and the concurrent-modification check (§10.4) relies on.

**Error codes** (domain `07`, spec 0000 §9). Errors use the standard body; besides the common codes, the case filing endpoints return:

| Code | Status | When |
| --- | --- | --- |
| `E07001` | 409 | The case has been submitted, so it can no longer be changed. |
| `E07002` | 400 | A document type, evidence type or details section this case's type does not accept (`field` names which). |
| `E07003` | 400 | `case_document_id` is not an active document of the same case. |
| `E07004` | 409 | The case is not in the status this step starts from (§7, §8). |
| `E07005` | 400 | Submit for signing: the filing is incomplete. One error per gap, on its part of the filing (`participants.accused`, `documents.VAKALATNAMA` …), as `POST /validate` lists them (§6.3). |
| `E07006` | 400 | Submit for payment: a signer has not signed. One error per signer, on `participants.<id>`. |
| `E07007` | 409 | The participant has already signed (§8). |
| `E07008` | 400 | Only complainants and POA holders sign the filing (§8). |
| `E07009` | 400 | No completed e-signature of this case's filing produced the document (§8). |
| `E07010` | 400 | A referenced participant is not an active participant of this case. |
| `E07011` | 400 | A party is listed more than once. |
| `E07012` | 400 | Only a complainant or an accused may be an institution. |
| `E07013` | 400 | The person or institution already holds this role on the case. |
| `E07014` | 400 | The person or institution would be both a complainant and an accused. |
| `E07015` | 400 | The participant cannot be removed while an active witness is called by them. |
| `E07016` | 400 | The participant does not have the role this needs (a complainant or an accused; a witness; a POA holder). |
| `E07017` | 400 | The person is already a witness called by this party. |
| `E07018` | 400 | A party cannot act for themselves (a POA holder for themselves, an advocate for themselves). |
| `E07019` | 400 | The filer cannot name themselves as accused. |
| `E07020` | 400 | The POA holder or advocate already acts for this party. |
| `E07021` | 400 | The advocate is not approved. |
| `E07022` | 400 | A party appearing in person cannot have an advocate (nor be marked in person while they have one). |
| `E07023` | 400 | The field does not apply to this participant (witness fields on another role, `is_party_in_person` on a witness or POA holder, a designation without an institution). |
| `E07024` | 400 | The field is not accepted by this endpoint, or cannot be changed. |
| `E07025` | 400 | Both `person` and `"self": true` were sent. |
| `E07026` | 400 | The signed document is already recorded for another participant (§8). |
| `E07027` | 400 | The e-sign transaction's signer is not the participant's user account (§8). |
| `E07028` | 400 | The e-signature was completed before the case entered `PENDING_SIGN` (§8). |

A details section or `evidence_info` that breaks its schema is reported with common codes (`E00002` missing key, `E00012` wrong type, `E00005` value not allowed, `E00001` otherwise), each on the path to the offending value, such as `evidence_info.cheque_number`.

```
POST /cases/{case_id}/submit-for-signing
POST /cases/{case_id}/submit-for-payment
POST /cases/{case_id}/submit-for-scrutiny
```

**Implementation Options:**

**(a) Dedicated endpoints in this service:**
Each transition validates preconditions and updates `cases.status`:
- `submit-for-signing`: Requires validation to pass (§6.3)
- `submit-for-payment`: Requires all participants to have `has_signed = true`
- `submit-for-scrutiny`: Requires payment confirmation

**(b) Delegate to workflow service:**
Call the existing workflow service (spec 0011) with a transition event. The workflow service owns status changes and enforces state machine rules.

**Recommendation:** Start with (a) for simplicity. The status values and transitions are well-defined (spec 0017 §7.3), so reimplementing them here is low risk. Migrate to (b) if other case types introduce complex branching or approval chains.

## 8. Signing

After submission for signing, parties e-sign the case:

```
POST /cases/{case_id}/participants/{case_participant_id}/sign
```

**Request Body:**
```json
{
  "signature_document_id": "uuid-from-esign-service"
}
```

**Response (200 OK):**
```json
{
  "case_participant_id": "uuid",
  "has_signed": true,
  "signed_at": "2024-03-16T10:00:00Z",
  "signature_document_id": "uuid"
}
```

**Implementation:**
Integration with eSign service (spec 0015) is assumed to happen before this call; this endpoint records the outcome. `signature_document_id` is the signed filing the e-sign service stored (`esign_transaction.signed_file_id`). It is accepted only when a `SUCCESS` e-sign transaction produced it for this case's filing (`entity_type = CASE_FILING`, `entity_id = case_id`); otherwise `400`.

The call sets `case_participant.has_signed = true` and stores the file as `case_participant.signature_document_id` (spec 0020 §4), so each signed copy stays linked to the participant who signed it. When it was signed is recorded on that e-sign transaction (`completed_at`), not repeated here; the response's `signed_at` is read from it.

Only complainants and POA holders sign; the accused and witnesses never do, so signing one of them is `400` (`E07008`). Signing is accepted only while the case is `PENDING_SIGN` (`409`, `E07004` otherwise), and once per participant (`409`, `E07007`). A document no matching e-sign transaction produced is `400` (`E07009`).

One e-signed document stands for one signer, so a matching transaction is still refused when:

- the document is already recorded as another participant's `signature_document_id` (`400`, `E07026`);
- the participant's person has a user account and the transaction's `signer` is a different user (`400`, `E07027`); a person without an account is not matched;
- the transaction's `completed_at` is before the case entered `PENDING_SIGN` (`400`, `E07028`), so a signature of an earlier draft is never accepted.

When every active complainant and POA holder has `has_signed = true`, the case can advance to `PENDING_PAYMENT`.

## 9. Design Decisions and Open Questions

### 9.1 Lazy Case Creation Pattern

**Decision:**
Case records (`cases` table and type-specific detail table) are created only when the user saves their first piece of substantive data, not when they click "start filing."

**Rationale:**
- **Reduces database clutter:** Users may click "start filing" and then abandon the process without entering any data. Creating database entries immediately would leave orphaned draft records with no content.
- **User experience:** Users often need time to gather documents and information. They may start the process on one device and resume on another, or may pause for hours or days before continuing.
- **Atomicity:** The first data entry and case creation happen in a single transaction, ensuring every case in the database has at least one piece of data.

**Implementation:**
1. `POST /cases` creates a `draft_session_id` stored in Redis/cache with metadata (case_type, created_by, timestamp).
2. First data-entry endpoint (documents, participants, evidence, details) checks if path parameter is:
   - A `case_id` (exists in database) → proceed normally
   - A `draft_session_id` (exists in cache) → atomically create case + detail table, then proceed with data entry
3. Client stores the returned `case_id` and uses it for all subsequent operations.

**Tradeoffs:**
- **Pro:** Cleaner database, fewer abandoned drafts
- **Pro:** Better reflects user intent (case starts when they commit to it)
- **Con:** Slightly more complex endpoint logic (ID resolution at each entry point)
- **Con:** Draft sessions in cache can be lost if cache expires (24hr TTL is acceptable given user can restart)

**Alternative considered:** Create case immediately on `POST /cases`
- Simpler endpoint logic
- But creates many orphaned drafts for abandoned filings
- Rejected in favor of lazy creation

### 9.2 Per-Role Endpoints vs. Single Participant Endpoint

This spec uses **per-role endpoints**:
- `POST /cases/{id}/complainants`
- `POST /cases/{id}/accused`
- `POST /cases/{id}/witnesses`

**Alternative:** Single endpoint with `role` in body:
```
POST /cases/{id}/participants
{
  "role": "COMPLAINANT",
  "person": { ... }
}
```

**Tradeoffs:**

| Aspect | Per-Role | Single Endpoint |
|--------|----------|-----------------|
| Frontend clarity | Clear resource paths, easy to route | Requires body inspection |
| Schema validation | Tighter per-role schemas (witness has `called_by_participant_id`, complainant does not) | Must validate role-specific fields dynamically |
| Future extensibility | New roles = new endpoints | New roles = extend enum, no new routes |
| Spec 0017 alignment | Follows "no new X per case type" principle partially | Fully aligned with table design |

**Recommendation:** Per-role endpoints for MVP. The frontend benefits outweigh the routing overhead. Consolidate to single endpoint if the route proliferation becomes unmanageable.

### 9.3 Fixing ASSERTED Person Records

When the filer corrects a typo in an accused's name, only `case_participant.name_at_filing` changes. The `person` row keeps the typo at `verification_level = ASSERTED`.

**Is this a problem?**
No. Spec 0017 §2.5 says:
> The rule: match and reuse only when identity is proven; otherwise create a new row. Never update a person row to make a case record correct.

The `person` row is fixed when the accused registers and claims it themselves.

### 9.4 Handling Multiple Cheques

When a case has 3 cheques, does the client:
- (a) Call `POST /cases/{id}/evidence` three times, or
- (b) Send an array of cheques in one call?

**Recommendation:** (a) — three separate calls. This keeps the endpoint simple and aligns with PATCH (which updates one evidence row). Batch creation can be added later if performance requires it.

### 9.5 Address Auto-Fill Failure

If the India Post Pincode API is unavailable, should the call:
- (a) Fail with 503 Service Unavailable, or
- (b) Proceed with `district` and `state` left as client-provided values?

**Recommendation:** (b). Auto-fill is a convenience, not a hard dependency. Log the failure, proceed with user input, and validate format only (§10.2).

### 9.6 Preview Permission Model

Who can call `GET /cases/{case_id}`?
- The creator (`created_by`)
- Active participants (`case_participant.person_id → person.user_id`)
- Court staff (role-based)

**Recommendation:** Implement a `CasePermission` service:
```python
def can_view_case(user, case):
    return (
        case.created_by_id == user.id
        or case.participants.filter(person__user_id=user.id, is_active=True).exists()
        or user.has_perm('cases.view_any_case')
    )
```

## 10. Validation and Error Handling

Every error uses the standard body of spec 0000 §9.1: an `errors` array of
`{code, message, field}` items plus `meta`. The case filing codes (domain `07`)
are listed in §7.

A missing address for service of notice, a missing designation, or a party
write naming no one is `E00002` (required) on that field. Format errors (a
phone number, a PAN, a pincode) keep the common field codes.

### 10.1 Document Type Validation

Unknown `document_type` values are rejected with 400; a type the case's type
does not accept is `E07002`:

```json
{
  "errors": [
    {
      "code": "E07002",
      "message": "'AFFIDAVIT' is not accepted for CHEQUE_BOUNCE cases. Must be one of: BOUNCED_CHEQUE, ...",
      "field": "document_type"
    }
  ],
  "meta": {"timestamp": "...", "app_version": "...", "spec_version": "1.0"}
}
```

### 10.2 Address Validation

Pincode format is enforced (6 digits, not starting with 0):

```python
import re

def validate_pincode(pincode):
    if not re.match(r'^[1-9][0-9]{5}$', pincode):
        raise ValidationError("Pincode must be 6 digits and not start with 0")
```

### 10.3 Evidence Info Schema Validation

Use JSON Schema validation:

```python
from jsonschema import validate, ValidationError as JSONSchemaError

EVIDENCE_SCHEMAS = {
    "CHEQUE": { ... },  # from §5.2
    "RETURN_MEMO": { ... },
}

def validate_evidence_info(evidence_type, evidence_info):
    schema = EVIDENCE_SCHEMAS.get(evidence_type)
    if not schema:
        raise ValidationError(f"Unknown evidence_type: {evidence_type}")
    try:
        validate(instance=evidence_info, schema=schema)
    except JSONSchemaError as e:
        raise ValidationError(f"Invalid evidence_info: {e.message}")
```

### 10.4 Concurrent Modification

Use optimistic locking on `cases.updated_at`:

```
PATCH /case-participants/{participant_id}
If-Unmodified-Since: Wed, 15 Mar 2024 12:00:00 GMT
```

If the case was modified after that timestamp, return:
```
412 Precondition Failed
{
  "error": "ConcurrentModificationError",
  "detail": "The case was modified by another user. Refresh and try again."
}
```

## 11. Performance Considerations

### 11.1 Eager Loading

The preview endpoint (`GET /cases/{id}`) joins across many tables. Use `select_related` and `prefetch_related`:

```python
case = Case.objects.select_related(
    'cheque_bounce_case'
).prefetch_related(
    Prefetch('case_participant_set', queryset=CaseParticipant.objects.filter(is_active=True)),
    'representation_set__advocate',
    'poa_mandate_set',
    'case_evidence_set',
    'case_document_set__document'
).get(pk=case_id)
```

### 11.2 Pagination for Evidence and Documents

Evidence and document lists use the project's default page-number pagination
(spec 0000 §11), the same as `GET /cases`: 20 items per page, selected with
`page`:

```
GET /cases/{id}/evidence?evidence_type=CHEQUE&page=1
GET /cases/{id}/documents?page=2
```

But the full preview (`GET /cases/{id}`) returns everything — it's cached and intended for one-time assembly.

### 11.3 Database Indexes

Create indexes to support query patterns:

```sql
-- Joining evidence to cases
CREATE INDEX ON case_evidence (case_id, evidence_type, is_active);

-- Joining participants to cases
CREATE INDEX ON case_participant (case_id, role, is_active);

-- Finding a user's cases
CREATE INDEX ON cases (created_by, status);

-- Joining representations
CREATE INDEX ON representation (case_id, is_active);
CREATE INDEX ON representation (advocate_id, is_active);
```

## 12. Testing Scenarios

### 12.1 Happy Path

1. User creates draft: `POST /cases` with `case_type=CHEQUE_BOUNCE`
2. Uploads cheque scan: `POST /cases/{id}/documents` with `document_type=BOUNCED_CHEQUE`
3. Adds complainant: `POST /cases/{id}/complainants`
4. Adds accused: `POST /cases/{id}/accused`
5. Adds evidence: `POST /cases/{id}/evidence` with `evidence_type=CHEQUE`
6. Updates case details: `PUT /cases/{id}/details/jurisdiction_limitation`
7. Validates: `POST /cases/{id}/validate` → returns `is_valid: true`
8. Submits for signing: `POST /cases/{id}/submit-for-signing` → status becomes `PENDING_SIGN`

### 12.2 Validation Failures

- Submit without complainant → 400, "At least one complainant required"
- Submit without cheque evidence → 400, "At least one CHEQUE evidence required"
- Upload unknown document type → 400, "Invalid document_type"

### 12.3 Concurrent Modification

- User A opens preview
- User B adds a complainant
- User A tries to PATCH accused with stale `If-Unmodified-Since`
- Returns 412, user A refreshes and retries

### 12.4 Person Matching

- Filer adds themselves as complainant (`"self": true`) for the first time → their `person` is created from their account at `verification_level=VERIFIED`, linked to `user_id`
- Filer adds themselves again, on this or another case → the same `person` row is reused, unchanged
- Filer adds accused "John Doe" → new `person` row created with `verification_level=ASSERTED`, never matched
- Filer adds a company with a PAN that an existing institution has → that institution is linked; its stored details are not returned

## 13. API Summary

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/case-types` | Every case type: sections, document types, evidence schemas |
| GET | `/case-types/{case_type}` | One case type's sections, document types, evidence schemas |
| GET | `/cases/by-number/{case_number}` | Join existing case |
| GET | `/cases?status=...&created_by=me` | List user's filings (DB cases only) |
| POST | `/cases` | Initialize draft session (returns draft_session_id) |
| GET | `/cases/{id}` | Preview full filing |
| POST | `/cases/{id}/validate` | Completeness check |
| POST | `/cases/{id_or_draft}/documents` | Upload document (creates case if first action) |
| GET | `/cases/{id}/documents?document_type=` | List documents |
| DELETE | `/case-documents/{case_document_id}` | Remove document |
| POST | `/cases/{id_or_draft}/complainants` | Add complainant (creates case if first action) |
| POST | `/cases/{id_or_draft}/accused` | Add accused (creates case if first action) |
| POST | `/cases/{id_or_draft}/witnesses` | Add witness (creates case if first action) |
| POST | `/cases/{id_or_draft}/poa-holders` | Add POA holder and their mandates (creates case if first action) |
| GET | `/cases/{id}/participants?role=` | List participants, optionally of one role |
| PATCH | `/case-participants/{participant_id}` | Update a participant's case data (never the person) |
| DELETE | `/case-participants/{participant_id}` | Remove a participant (soft); renumbers that role |
| POST | `/cases/{id_or_draft}/advocates` | Add an advocate for one or more clients (creates case if first action) |
| GET | `/cases/{id}/representations` | List advocates and their clients |
| DELETE | `/representations/{representation_id}` | End a representation |
| GET | `/cases/{id}/poa-mandates` | List POA mandates |
| PATCH | `/poa-mandates/{mandate_id}` | Update a mandate's `poa_type` |
| DELETE | `/poa-mandates/{mandate_id}` | Revoke a mandate |
| POST | `/cases/{id_or_draft}/evidence` | Add evidence (creates case if first action) |
| PATCH | `/case-evidence/{case_evidence_id}` | Update evidence |
| DELETE | `/case-evidence/{case_evidence_id}` | Remove evidence |
| GET | `/cases/{id}/evidence?evidence_type=` | List evidence |
| PUT | `/cases/{id_or_draft}/details/{section}` | Update case details (creates case if first action) |
| GET | `/cases/{id}/details` | Get all case details |
| POST | `/cases/{id}/submit-for-signing` | Advance to signing |
| POST | `/cases/{id}/participants/{id}/sign` | Record signature |

## 14. References

- **Spec 0000**: API coding standards
- **Spec 0005**: User model and authentication
- **Spec 0011**: Case workflows
- **Spec 0014**: File storage service
- **Spec 0015**: eSign integration
- **Spec 0017**: Person, case filing, and evidence schema
- **India Post Pincode API**: https://api.postalpincode.in/pincode/{pincode}
