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
- `page`, `page_size`: Pagination (spec 0000)

**Response (200 OK):**
```json
{
  "results": [
    {
      "case_id": "uuid",
      "case_type": "CHEQUE_BOUNCE",
      "filing_number": "FIL/2024/001234",
      "status": "DRAFT_IN_PROGRESS",
      "created_at": "2024-03-10T14:22:00Z",
      "updated_at": "2024-03-12T09:15:00Z"
    }
  ],
  "meta": {
    "page": 1,
    "page_size": 20,
    "total_count": 1,
    "total_pages": 1
  }
}
```

**Note:**
This endpoint lists only cases that have been created in the database (i.e., have at least one saved data entry). Draft sessions (created via `POST /cases` but not yet populated with data) are not included in this listing because they exist only in cache, not in the `cases` table.

**POST /cases (Initialize Client-Side Draft):**

Initializes a client-side draft session without creating database entries. Database entries are created only when the user saves their first piece of actual information.

**Request Body:**
```json
{
  "case_type": "CHEQUE_BOUNCE"
}
```

**Response (201 Created):**
```json
{
  "draft_session_id": "550e8400-e29b-41d4-a716-446655440000",
  "case_type": "CHEQUE_BOUNCE",
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
     "created_by": "user_id",
     "created_at": "timestamp"
   }
   ```
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

Every upload requires a case ID and a `document_type`. Only **case-level documents** use these endpoints. Vakalatnamas and POA documents are uploaded when creating the representation/mandate (§4.5, §4.6).

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
- `400 Bad Request`: Unknown `document_type` or file validation failure
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
DELETE /cases/{case_id}/documents/{case_document_id}
```

**Response (204 No Content)**

**Implementation:**
Soft delete: sets `is_active = false`. The underlying `document` row is not deleted (spec 0017 §8.4).

### 3.4 Document Type Enum

The `document_type` must be one of:

**For cheque bounce cases:**
- `BOUNCED_CHEQUE`
- `RETURN_MEMO`
- `LEGAL_DEMAND_NOTICE`
- `PROOF_OF_DISPATCH`
- `PROOF_OF_DEBT`
- `AFFIDAVIT`
- `OTHER_SUPPORTING_DOCUMENT`

**Not accepted here:**
- `VAKALATNAMA` — uploaded with advocate representation (§4.5)
- `POA_DOCUMENT` — uploaded with POA mandate (§4.6)

New case types extend this enum without changing the endpoint.

## 4. Step 2: Party Management

All parties write to `case_participant` and differ only by `role`. This section uses **per-role endpoints** for frontend clarity; see §9.2 for the alternative single-endpoint design.

### 4.1 Complainants

```
POST   /cases/{case_id_or_draft_session_id}/complainants
PATCH  /cases/{case_id}/complainants/{case_participant_id}
DELETE /cases/{case_id}/complainants/{case_participant_id}
```

**POST Request Body:**
```json
{
  "person": {
    "person_id": "uuid-if-existing",
    "name": "Rajesh Kumar",
    "phone_number": "+919876543210",
    "email_address": "rajesh@example.com",
    "date_of_birth": "1985-06-15",
    "gender": "MALE",
    "relation": "S/O",
    "relative_name": "Ram Kumar"
  },
  "address": {
    "line1": "123 MG Road",
    "city": "Bangalore",
    "pincode": "560001",
    "district": "Bangalore Urban",
    "state": "Karnataka"
  },
  "organization_id": null,
  "is_party_in_person": false
}
```

**Response (201 Created):**
```json
{
  "case_participant_id": "uuid",
  "person_id": "uuid",
  "role": "COMPLAINANT",
  "ordinal": 1,
  "name_at_filing": "Rajesh Kumar",
  "phone_number_at_filing": "+919876543210",
  "gender_at_filing": "MALE",
  "address_id": "uuid",
  "is_party_in_person": false,
  "is_active": true,
  "created_at": "2024-03-15T12:00:00Z"
}
```

**Transaction Steps (spec 0017 §3):**

1. **Check if case exists and create if needed:**
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

2. **Resolve the person:**
   - If `person_id` provided and identity is proven (logged-in filer or OTP-verified), reuse that `person` row.
   - Otherwise, create new `person` with `verification_level = ASSERTED` and no attempt to match.
   - For complainants filing their own case: reuse the filer's person record at `verification_level = VERIFIED`.

3. **Write the address:**
   - Insert new `address` row with provided fields (immutable, spec 0017 §6).
   - Auto-fill `district` and `state` from pincode via India Post API.

4. **Create the participant:**
   - Insert `case_participant` with:
     - `person_id` or `organization_id`
     - `role = 'COMPLAINANT'`
     - Next free `ordinal` for this role on this case
     - Frozen snapshots: `name_at_filing`, `phone_number_at_filing`, `gender_at_filing`
     - `address_id` from step 3
     - `start_date = now()`

5. **Clear preview cache.**

**PATCH Request:**
Updates only the `case_participant` row. Never updates the `person` row.

**Request Body (partial):**
```json
{
  "name_at_filing": "Rajesh S. Kumar",
  "address": {
    "line1": "456 New Street",
    "city": "Bangalore",
    "pincode": "560002"
  }
}
```

**Implementation:**
- Changed name/phone/gender: update `*_at_filing` columns.
- Changed address: insert new `address` row, repoint `address_id`.
- `person` row is **never** updated to correct a case record (spec 0017 §3.4).

**DELETE:**
Soft delete: sets `is_active = false`, `end_date = now()`. Optionally renumber remaining participants to keep ordinals consecutive.

### 4.2 Accused

```
POST   /cases/{case_id_or_draft_session_id}/accused
PATCH  /cases/{case_id}/accused/{case_participant_id}
DELETE /cases/{case_id}/accused/{case_participant_id}
```

Same contract as complainants (§4.1), but `role = 'ACCUSED'`.

**Key Differences:**
1. For accused, always create a **new person** with `verification_level = ASSERTED`. Never attempt to match an existing person, because the accused is being named by the complainant, not self-identifying.
2. POST endpoint accepts `case_id_or_draft_session_id` and creates the case atomically if this is the first action (same transaction steps as §4.1, step 1).

### 4.3 Witnesses

```
POST   /cases/{case_id_or_draft_session_id}/witnesses
PATCH  /cases/{case_id}/witnesses/{case_participant_id}
DELETE /cases/{case_id}/witnesses/{case_participant_id}
```

**POST Request Body (extends complainant body):**
```json
{
  "person": { ... },
  "address": { ... },
  "called_by_participant_id": "uuid-of-complainant-or-accused",
  "what_will_prove": "Eyewitness to the transaction on 2024-01-15"
}
```

**Implementation:**
- POST endpoint accepts `case_id_or_draft_session_id` and creates the case atomically if this is the first action (same transaction steps as §4.1, step 1)
- `role = 'WITNESS'`
- `called_by_participant_id` stored directly on `case_participant`
- `what_will_prove` stored in `additional_details` JSONB as:
  ```json
  {
    "what_will_witness_prove": "Eyewitness to the transaction on 2024-01-15"
  }
  ```

### 4.4 Representation (Advocates)

```
POST   /cases/{case_id_or_draft_session_id}/advocates
PATCH  /cases/{case_id}/advocates/{representation_id}
DELETE /cases/{case_id}/advocates/{representation_id}
```

**POST Request Body:**
```json
{
  "advocate_id": "uuid",
  "client_participant_ids": ["uuid1", "uuid2", "uuid3"],
  "vakalatnama_file": "<multipart file>"
}
```

**Response (201 Created):**
```json
{
  "representation_ids": ["uuid1", "uuid2", "uuid3"],
  "advocate_id": "uuid",
  "vakalatnama_document_id": "uuid"
}
```

**Transaction Steps:**
1. **Check if case exists and create if needed:**
   - If path parameter is a valid `case_id`, proceed with existing case
   - If path parameter is a `draft_session_id`, atomically create case and type-specific table (same as §4.1, step 1)

2. Upload `vakalatnama_file` to storage, get `vakalatnama_document_id`.

3. For each `client_participant_id`:
   - Insert `representation` row with:
     - `case_id` (denormalized from participant)
     - `advocate_id`
     - `case_participant_id`
     - `vakalatnama_document_id`
     - `is_active = true`
     - `from_date = now()`

4. Return array of created `representation_ids`.

**Why multiple rows:**
Three clients = three rows with the same `advocate_id`. Spec 0017 §5 explains the design.

**PATCH:**
Updates `vakalatnama_document_id` only. Changing the advocate or client requires DELETE + POST.

**DELETE:**
Sets `is_active = false`, `to_date = now()`. Rows are never hard-deleted (spec 0017 §5.3).

### 4.5 Power of Attorney Holders

```
POST   /cases/{case_id_or_draft_session_id}/poa-holders
PATCH  /cases/{case_id}/poa-holders/{poa_mandate_id}
DELETE /cases/{case_id}/poa-holders/{poa_mandate_id}
```

**POST Request Body:**
```json
{
  "person": {
    "person_id": "uuid-if-existing",
    "name": "Suresh Patel",
    "phone_number": "+919123456789",
    ...
  },
  "address": { ... },
  "represented_participant_ids": ["uuid1", "uuid2"],
  "poa_type": "Limited to this case only",
  "poa_document_file": "<multipart file>"
}
```

**Response (201 Created):**
```json
{
  "case_participant_id": "uuid",
  "poa_mandate_ids": ["uuid1", "uuid2"],
  "person_id": "uuid",
  "role": "POA_HOLDER"
}
```

**Transaction Steps:**
1. **Check if case exists and create if needed:**
   - If path parameter is a valid `case_id`, proceed with existing case
   - If path parameter is a `draft_session_id`, atomically create case and type-specific table (same as §4.1, step 1)

2. Resolve person (POAs are OTP-verified at filing, so existing person can be matched).

3. Create `case_participant` with `role = 'POA_HOLDER'`.

4. Upload `poa_document_file` to storage.

5. For each `represented_participant_id`:
   - Insert `poa_mandate` row with:
     - `case_id` (denormalized)
     - `poa_participant_id` (the participant created in step 3)
     - `represented_participant_id`
     - `poa_type`
     - `document_id` (from step 4)
     - `is_active = true`
     - `granted_at = now()`

**Why multiple mandate rows:**
One POA acting for 2 of 3 complainants = 2 `poa_mandate` rows pointing to the same `poa_participant_id` (spec 0017 §4).

**DELETE:**
Sets `is_active = false`, `revoked_at = now()`.

## 5. Step 3: Case Details and Evidence

### 5.1 Evidence (Sections 1 & 2: Cheques, Notices)

```
POST   /cases/{case_id_or_draft_session_id}/evidence
PATCH  /cases/{case_id}/evidence/{case_evidence_id}
DELETE /cases/{case_id}/evidence/{case_evidence_id}
GET    /cases/{case_id}/evidence?evidence_type={type}
```

**POST Request Body (Cheque):**
```json
{
  "evidence_type": "CHEQUE",
  "case_document_id": "uuid-of-uploaded-scan",
  "evidence_info": {
    "cheque_number": "456789",
    "bank_account_number": "1234567890",
    "drawee_bank": "State Bank of India",
    "amount": 50000.00,
    "cheque_date": "2024-01-15",
    "return_memo_date": "2024-01-22"
  }
}
```

**POST Request Body (Demand Notice):**
```json
{
  "evidence_type": "LEGAL_DEMAND_NOTICE",
  "case_document_id": "uuid",
  "evidence_info": {
    "notice_date": "2024-02-01",
    "dispatch_date": "2024-02-01",
    "dispatch_method": "Registered post",
    "tracking_number": "RR123456789IN"
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
1. **Check if case exists and create if needed:**
   - If path parameter is a valid `case_id`, proceed with existing case
   - If path parameter is a `draft_session_id`, atomically create case and type-specific table (same as §4.1, step 1)

2. Validate `evidence_info` against predefined schema for `evidence_type` (§5.2).

3. Assign next `ordinal` for `(case_id, evidence_type)`.

4. Insert `case_evidence` row.

5. Clear preview cache.

**Why one endpoint for all evidence:**
New case types add new `evidence_type` values and their schemas, not new endpoints or tables. This replaces type-specific calls like `POST /cheque_bounce`.

**PATCH:**
Updates `evidence_info` only. Changing `evidence_type` is not allowed; delete and recreate instead.

**DELETE:**
Soft delete: sets `is_active = false`.

**GET:**
Lists evidence, optionally filtered by `evidence_type`.

### 5.2 Evidence Info Schemas

Each `evidence_type` has a required schema validated on POST/PATCH:

**`CHEQUE`:**
```json
{
  "type": "object",
  "required": ["cheque_number", "bank_account_number", "drawee_bank", "amount", "cheque_date"],
  "properties": {
    "cheque_number": { "type": "string" },
    "bank_account_number": { "type": "string" },
    "drawee_bank": { "type": "string" },
    "amount": { "type": "number", "minimum": 0 },
    "cheque_date": { "type": "string", "format": "date" },
    "return_memo_date": { "type": "string", "format": "date" }
  }
}
```

**`RETURN_MEMO`:**
```json
{
  "type": "object",
  "required": ["return_reason", "return_date", "bank_name"],
  "properties": {
    "return_reason": { "type": "string" },
    "return_date": { "type": "string", "format": "date" },
    "bank_name": { "type": "string" }
  }
}
```

**`LEGAL_DEMAND_NOTICE`:**
```json
{
  "type": "object",
  "required": ["notice_date", "dispatch_date", "dispatch_method"],
  "properties": {
    "notice_date": { "type": "string", "format": "date" },
    "dispatch_date": { "type": "string", "format": "date" },
    "dispatch_method": { "type": "string" },
    "tracking_number": { "type": "string" }
  }
}
```

### 5.3 Case Details (Sections 3 & 4: Type-Specific JSON)

```
PUT /cases/{case_id_or_draft_session_id}/details/{section}
GET /cases/{case_id}/details
```

**PUT Request Body (Section 3: Jurisdiction & Limitation):**
```json
{
  "jurisdiction_grounds": "Cheque dishonored within territorial jurisdiction",
  "limitation_compliance": true,
  "limitation_notes": "Demand notice sent within 30 days of dishonor"
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
1. **Check if case exists and create if needed:**
   - If path parameter is a valid `case_id`, proceed with existing case
   - If path parameter is a `draft_session_id`, atomically create case and type-specific table (same as §4.1, step 1)

2. Validate `{section}` against allowed columns for this `case_type`:
   - For `CHEQUE_BOUNCE`: `jurisdiction_limitation`, `adr_other_prayer`

3. Replace that JSONB column on the type-detail table (`cheque_bounce_case.jurisdiction_limitation`).

4. Clear preview cache.

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
      "vakalatnama_document_id": "uuid",
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
   - Each active `representation` has a `vakalatnama_document_id`

3. **POA Mandates:**
   - Each active `poa_mandate` has a `document_id`

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
  "signed_at": "2024-03-16T10:00:00Z"
}
```

**Implementation:**
Sets `case_participant.has_signed = true`. Integration with eSign service (spec 0015) is assumed to happen before this call; this endpoint records the outcome.

When all participants have `has_signed = true`, the case can advance to `PENDING_PAYMENT`.

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

### 10.1 Document Type Validation

Unknown `document_type` values are rejected with 400:

```json
{
  "error": "ValidationError",
  "detail": {
    "document_type": [
      "Invalid document type 'UNKNOWN_TYPE'. Must be one of: BOUNCED_CHEQUE, RETURN_MEMO, ..."
    ]
  }
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
PATCH /cases/{id}/complainants/{participant_id}
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

If a case has many cheques or documents, paginate the lists:

```
GET /cases/{id}/evidence?evidence_type=CHEQUE&page=1&page_size=10
GET /cases/{id}/documents?page=1&page_size=20
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

- Filer creates case (person created with `verification_level=VERIFIED`, linked to `user_id`)
- Filer adds themselves as complainant → existing `person` row is reused
- Filer adds accused "John Doe" → new `person` row created with `verification_level=ASSERTED`

## 13. API Summary

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/cases/by-number/{case_number}` | Join existing case |
| GET | `/cases?status=...&created_by=me` | List user's filings (DB cases only) |
| POST | `/cases` | Initialize draft session (returns draft_session_id) |
| GET | `/cases/{id}` | Preview full filing |
| POST | `/cases/{id}/validate` | Completeness check |
| POST | `/cases/{id_or_draft}/documents` | Upload document (creates case if first action) |
| GET | `/cases/{id}/documents?document_type=` | List documents |
| DELETE | `/cases/{id}/documents/{doc_id}` | Remove document |
| POST | `/cases/{id_or_draft}/complainants` | Add complainant (creates case if first action) |
| PATCH | `/cases/{id}/complainants/{participant_id}` | Update complainant |
| DELETE | `/cases/{id}/complainants/{participant_id}` | Remove complainant |
| POST | `/cases/{id_or_draft}/accused` | Add accused (creates case if first action) |
| PATCH | `/cases/{id}/accused/{participant_id}` | Update accused |
| DELETE | `/cases/{id}/accused/{participant_id}` | Remove accused |
| POST | `/cases/{id_or_draft}/witnesses` | Add witness (creates case if first action) |
| PATCH | `/cases/{id}/witnesses/{participant_id}` | Update witness |
| DELETE | `/cases/{id}/witnesses/{participant_id}` | Remove witness |
| POST | `/cases/{id_or_draft}/advocates` | Add advocate (creates case if first action) |
| PATCH | `/cases/{id}/advocates/{representation_id}` | Update representation |
| DELETE | `/cases/{id}/advocates/{representation_id}` | End representation |
| POST | `/cases/{id_or_draft}/poa-holders` | Add POA holder (creates case if first action) |
| PATCH | `/cases/{id}/poa-holders/{mandate_id}` | Update POA mandate |
| DELETE | `/cases/{id}/poa-holders/{mandate_id}` | Revoke mandate |
| POST | `/cases/{id_or_draft}/evidence` | Add evidence (creates case if first action) |
| PATCH | `/cases/{id}/evidence/{evidence_id}` | Update evidence |
| DELETE | `/cases/{id}/evidence/{evidence_id}` | Remove evidence |
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
