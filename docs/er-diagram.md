# Dristi Backend — Entity-Relationship Diagram

Version: 0.1
Last updated on 2026-11-26


Mermaid `erDiagram` sources for the whole schema, one diagram per domain. GitHub
renders these in place; locally use any Mermaid-capable Markdown viewer or
`mmdc -i er-diagram.md`.

## Conventions

- Every entity inherits `apps.core.models.BaseModel` unless noted:
  `id UUID PK`, `created_at`, `updated_at`, and audit FKs
  `created_by` / `updated_by` → `users_user`. These audit columns are **omitted**
  from all diagrams to keep them readable.
- Auditable entities (`BaseAuditableModel`) each get a shadow `*_historical*`
  table from django-simple-history (full row copy + `history_id`,
  `history_date`, `history_type`, `history_user`). Also omitted.
- Soft-delete flag `is_active` is shown only where it drives business rules or
  conditional unique constraints.
- Some models reference other data by **plain id column** (no database FK) by
  design — shown with dashed lines and a `(logical)` label.
- Table names follow Django's default: `<app>_<model>` (e.g. `CASE` →
  `cases_case`, `CASE_PARTICIPANT` → `cases_caseparticipant`).
- Bare boxes (no attributes) are entities defined in another section, included
  to show the relationship.

## Domain map

```mermaid
flowchart TB
    subgraph identity[Identity]
        USERS[users]
        PARTIES[parties]
        ADDRESS[address]
    end
    subgraph reference[Reference data]
        CORE[core]
        ORG[organizations]
        LOC[locations]
        FILES[files]
    end
    subgraph domain[Court domain]
        CASES[cases]
        HEARINGS[hearings]
        SCRUTINY[scrutiny]
        PAYMENTS[payments]
    end
    subgraph support[Support services]
        REQUESTS[dristi_requests]
        ESIGN[esign]
        PDF[pdf]
        MESSAGING[messaging]
        NOTIFICATIONS[notifications]
        CMS[cms]
    end

    PARTIES --> USERS
    ADDRESS --> USERS
    ORG --> LOC
    FILES --> ORG
    FILES --> USERS
    CASES --> PARTIES
    CASES --> USERS
    CASES --> ORG
    CASES --> ADDRESS
    CASES --> FILES
    HEARINGS --> CASES
    HEARINGS --> ORG
    SCRUTINY --> CASES
    SCRUTINY --> CORE
    PAYMENTS --> CASES
    REQUESTS --> USERS
    REQUESTS --> FILES
    ESIGN --> USERS
    PDF --> ORG
    PDF --> USERS
    NOTIFICATIONS --> USERS
```

---

## 1. Identity — `users` (spec 0005)

One account (`User`, login by mobile number) with exactly one profile row for
its role. `Person` (section 2) is the human being; `User` is the login. A
person claims an account when they register.

```mermaid
erDiagram
    USER ||--o| LITIGANT_PROFILE : "role = LITIGANT"
    USER ||--o| POWER_OF_ATTORNEY_PROFILE : "role = POWER_OF_ATTORNEY"
    USER ||--o| ADVOCATE_PROFILE : "role = ADVOCATE"
    USER ||--o| CLERK_PROFILE : "role = CLERK"

    USER {
        UUID id PK
        string mobile_number UK "E.164, +91 only"
        string name
        string email UK "nullable"
        string role "LITIGANT, POWER_OF_ATTORNEY, ADVOCATE, CLERK"
        string registration_status "PENDING_PROFILE, COMPLETE"
        datetime terms_accepted_at
        int terms_version_accepted
        bool is_active
        bool is_staff
    }
    LITIGANT_PROFILE {
        UUID id PK
        UUID user FK "OneToOne"
        string name
    }
    POWER_OF_ATTORNEY_PROFILE {
        UUID id PK
        UUID user FK "OneToOne"
        string name
    }
    ADVOCATE_PROFILE {
        UUID id PK
        UUID user FK "OneToOne"
        string name
        string bar_registration_id UK "unverified claim"
        string advocate_type "CIVIL, CRIMINAL"
        string approval_status "PENDING, ACCEPTED, REJECTED"
    }
    CLERK_PROFILE {
        UUID id PK
        UUID user FK "OneToOne"
        string name
        string clerk_registration_number UK "unverified claim"
        string approval_status "PENDING, ACCEPTED, REJECTED"
    }
```

## 2. Parties & addresses — `parties`, `address` (spec 0020 §2-3, §7)

`Person` and `Institution` hold *current* data and are shared across filings;
each case freezes its own snapshot in `CaseParticipant`. `Address` rows are
immutable and deduplicated by content hash: an edit creates a new row and the
caller repoints its FK (`Address.revise()`).

```mermaid
erDiagram
    USER ||--o| PERSON : "claims on registration"
    INSTITUTION ||--o{ PERSON : "staff (designation)"
    USER ||--o{ ADDRESS : "created_by (PROTECT)"

    PERSON {
        UUID id PK
        UUID user FK "OneToOne, NULL until registered"
        UUID institution FK "PROTECT, optional employer"
        string name "optional: witness may be designation-only"
        string phone_number "E.164"
        string email_address
        string relation "SON_OF, DAUGHTER_OF, WIFE_OF, HUSBAND_OF, WARD_OF"
        string relative_name
        date date_of_birth
        int age "approximate; cleared when DOB is set"
        string gender "MALE, FEMALE, OTHER"
        string designation "only with institution"
        bool disability_status "NULL = unanswered"
        string verification_level "ASSERTED, CONTACTED, VERIFIED"
    }
    INSTITUTION {
        UUID id PK
        string entity_type "company, firm, society, ..."
        string entity_name
        string pan UK "re-matching key; NULL never clashes"
        string cin UK "re-matching key"
        bool pan_cin_skip_declared
    }
    ADDRESS {
        UUID id PK
        string line1
        string city
        string state
        string pincode
        string district
        string police_station
        string hash UK "SHA-256 of canonical content; dedup key"
        datetime created_at
        UUID created_by FK "PROTECT; immutable row"
    }
```

## 3. Reference data — `organizations`, `locations`, `files`, `core`

```mermaid
erDiagram
    ORGANIZATION ||--o{ ORGANIZATION : "parent (court hierarchy)"
    ORGANIZATION }o--o{ LOCATION : "jurisdictions (M2M)"
    LOCATION ||--o{ LOCATION : "parent (administrative hierarchy)"
    ORGANIZATION ||--o{ FILE : "owns"
    USER ||--o{ FILE : "uploads"
    FILE }o--o{ FILE_TAG : "tags (M2M)"
    DJANGO_CONTENT_TYPE ||--o{ ADDITIONAL_ATTRIBUTE : "extends a model"

    ORGANIZATION {
        UUID id PK
        string code UK "upper snake, e.g. KL_HIGH_COURT"
        string organization_type "supreme_court ... magistrate_court"
        string name
        string short_name
        string description
        UUID parent FK "PROTECT, self; NULL = root"
        bool is_active
        json additional_attributes "typed, via AdditionalAttribute"
    }
    LOCATION {
        UUID id PK
        string code UK "e.g. IN_KL, IFSC for banks"
        string name
        string short_name
        string location_type "country, state, district, pincode, bank, police_station"
        UUID parent FK "PROTECT, self"
        bool is_active
        json additional_attributes
    }
    FILE {
        UUID id PK
        UUID organization FK "PROTECT, optional"
        UUID user FK "PROTECT, uploader"
        string file_type "pdf, document, image, signature, digitally_signed"
        string file_name
        string content_type
        bigint file_size
        string storage_path UK "object-storage key"
        bool is_active
    }
    FILE_TAG {
        UUID id PK
        string name UK "slugified"
    }
    LANGUAGE {
        UUID id PK
        string code UK "BCP 47, e.g. en, ml"
        string name
        string native_name
        bool is_default "exactly one row"
        int sort_order
        json supports "ui, translation, ocr"
        bool is_active
    }
    CONFIGURATION {
        UUID id PK
        string config_set "UK with config_key"
        string config_key "UK with config_set"
        string config_value
        string description
        bool is_active
    }
    PUBLIC_CONFIGURATION {
        UUID id PK
        string config_set "UK with config_key"
        string config_key "UK with config_set"
        string config_value "served to internet clients"
        string value_type "string, integer, boolean, json"
        string description
        bool is_active
    }
    BUSINESS_RULE {
        UUID id PK
        string code UK "upper snake; referenced by code, never FK"
        string name
        string description
        string engine "rule_engine, gorules"
        string rule_expression
        json rule_input_schema
        json rule_output_schema
        bool is_active
    }
    ADDITIONAL_ATTRIBUTE {
        UUID id PK
        int content_type FK "django_content_type"
        string name "UK with content_type"
        string data_type
        bool is_nullable
        json default_value
    }
    API_VERSION_CHANGE_LOG {
        UUID id PK
        string version
        string change_log
        bool is_active
    }
```

## 4. Cases — `cases` (spec 0020)

The central aggregate. `Case` holds only what every dispute type shares;
per-type details live in 1:1 extension rows (`ChequeBounceCase`, shared primary
key). Participants, contacts, documents and evidence are soft-deleted
(`is_active = False`), never hard-deleted.

```mermaid
erDiagram
    USER ||--o{ CASE : "filer (created_by, PROTECT)"
    ORGANIZATION ||--o{ CASE : "court (PROTECT)"
    CASE ||--o| CHEQUE_BOUNCE_CASE : "type details (shared PK)"
    CASE ||--o{ CASE_PARTICIPANT : "participants"
    PERSON ||--o{ CASE_PARTICIPANT : "individual or representative"
    INSTITUTION ||--o{ CASE_PARTICIPANT : "institution party"
    CASE_PARTICIPANT ||--|| WITNESS : "witness extras (shared PK)"
    FILE ||--o{ CASE_PARTICIPANT : "signature_document"
    CASE ||--o{ POA_MANDATE : "mandates"
    CASE_PARTICIPANT ||--o{ POA_MANDATE : "holder (poa_participant)"
    CASE_PARTICIPANT ||--o{ POA_MANDATE : "represented party"
    CASE ||--o{ REPRESENTATION : "advocates on case"
    CASE_PARTICIPANT ||--o{ REPRESENTATION : "client"
    ADVOCATE_PROFILE ||--o{ REPRESENTATION : "advocate (PROTECT)"
    CASE ||--o{ CASE_CONTACT : "contacts"
    CASE_PARTICIPANT ||--o{ CASE_CONTACT : "person's contacts"
    INSTITUTION ||--o{ CASE_CONTACT : "institution's own per-case contacts"
    ADDRESS ||--o{ CASE_CONTACT : "postal address (PROTECT)"
    CASE ||--o{ CASE_DOCUMENT : "documents"
    FILE ||--o{ CASE_DOCUMENT : "stored file (PROTECT)"
    CASE_PARTICIPANT ||--o{ CASE_DOCUMENT : "owner (id proof, vakalatnama, POA)"
    CASE ||--o{ CASE_EVIDENCE : "evidence"
    CASE_DOCUMENT ||--o| CASE_EVIDENCE : "scan of (case_document; one active item per scan)"
    CASE_EVIDENCE ||--o{ CASE_DOCUMENT : "supporting docs (case_evidence)"
    CASE ||--o{ COMPLAINT_SIGNING_PACKAGE : "signing rounds"
    FILE ||--o{ COMPLAINT_SIGNING_PACKAGE : "complaint_file / signing_file / current_file"

    CASE {
        UUID id PK "kept from draft session"
        UUID created_by FK "filer; PROTECT, required"
        string case_type "e.g. CHEQUE_BOUNCE"
        string filing_number UK "nullable"
        string case_number UK "nullable"
        string cnr_number UK "nullable"
        string status "e-filing lifecycle"
        UUID court FK "Organization; PROTECT"
        datetime filed_at
        datetime registered_at
        string affidavit "rich text"
    }
    CASE_PARTICIPANT {
        UUID id PK
        UUID case FK
        UUID person FK "PROTECT; person, institution or both"
        UUID institution FK "PROTECT"
        string role "COMPLAINANT, ACCUSED, WITNESS, POA_HOLDER"
        int ordinal "UK(case, role, ordinal) where active"
        string name_at_filing "frozen snapshot"
        string gender_at_filing
        int age_at_filing
        string designation_at_filing
        string entity_name_at_filing
        datetime start_date
        datetime end_date "soft removal"
        bool is_active
        bool is_party_in_person
        bool poa_given
        bool resides_within_jurisdiction "accused only"
        bool contact_details_unknown_declared
        bool institution_contact_details_unknown_declared
        bool has_signed
        UUID signature_document FK "File; PROTECT"
    }
    WITNESS {
        UUID case_participant PK "OneToOne, shared PK"
        string side "COMPLAINANT, ACCUSED"
        string what_will_witness_prove
    }
    POA_MANDATE {
        UUID id PK
        UUID case FK
        UUID poa_participant FK "holder; CASCADE"
        UUID represented_participant FK "party; CASCADE"
        datetime granted_at
        datetime revoked_at "revoke = soft delete"
        bool is_active "UK(poa_participant, represented_participant) where active"
    }
    REPRESENTATION {
        UUID id PK
        UUID case FK
        UUID advocate FK "AdvocateProfile; PROTECT"
        UUID case_participant FK "client; CASCADE"
        datetime from_date
        datetime to_date
        bool is_active "UK(advocate, case_participant) where active"
    }
    CASE_CONTACT {
        UUID id PK
        UUID case FK
        UUID case_participant FK "owner, or NULL"
        UUID institution FK "owner or co-owner; PROTECT"
        string contact_type "MOBILE_NUMBER, EMAIL, ADDRESS, PERMANENT_ADDRESS"
        string value "phone/email; NULL for addresses"
        UUID address FK "Address; PROTECT"
        int ordinal "1 = primary"
        bool is_active
    }
    CASE_DOCUMENT {
        UUID id PK
        UUID case FK
        UUID document FK "files.File; PROTECT. UK(case, document)"
        string document_type "per case-type config"
        UUID case_participant FK "optional owner"
        UUID case_evidence FK "optional supported evidence"
        json additional_details
        bool is_active
    }
    CASE_EVIDENCE {
        UUID id PK
        UUID case FK
        UUID case_document FK "its own scan; SET_NULL"
        string evidence_type "e.g. cheque, demand notice"
        int ordinal "UK(case, evidence_type, ordinal) where active"
        json evidence_info "validated against evidence schema"
        json additional_details
        bool is_active
    }
    CHEQUE_BOUNCE_CASE {
        UUID case PK "OneToOne, shared PK"
        json jurisdiction_limitation "form section"
        json adr_other_prayer "form section"
        json additional_details
    }
    COMPLAINT_SIGNING_PACKAGE {
        UUID id PK
        UUID case FK
        int signing_round "UK(case, signing_round)"
        string status "OPEN, COMPLETE, SUPERSEDED; one OPEN per case"
        UUID complaint_file FK "rendered complaint PDF"
        UUID signing_file FK "complaint + all documents"
        UUID current_file FK "gathers signatures"
        int page_count
        int affidavit_page
        json signatories
        json placeholders "signature boxes by participant id"
        json document_ids
    }
    CASE_NUMBER_SERIES {
        UUID id PK
        string series "UK with year"
        int year "UK with series"
        int last_number
    }
```

## 5. Hearings — `hearings` (spec 0023)

`Hearing` rows are moved in place and never deleted; every end is a status and
`HearingDateChange` is the append-only adjournment log.

```mermaid
erDiagram
    CASE ||--o{ HEARING : "listed as"
    ORGANIZATION ||--o{ HEARING : "court"
    HEARING_PURPOSE ||--o{ HEARING : "purpose"
    HEARING ||--o{ HEARING : "previous_hearing (fixed by its order)"
    HEARING ||--o{ HEARING : "moves_hearing (provisional hold)"
    HEARING ||--o{ HEARING_ATTENDANCE : "roll"
    HEARING ||--o{ HEARING_DATE_CHANGE : "adjournment log"
    HEARING_PURPOSE ||--o{ HEARING_DATE_CHANGE : "from_purpose / to_purpose"
    ORGANIZATION ||--o{ BULK_RESCHEDULE_JOB : "court"
    USER ||--o{ BULK_RESCHEDULE_JOB : "confirmed_by"
    BULK_RESCHEDULE_JOB ||--o{ BULK_RESCHEDULE_ITEM : "items"
    HEARING ||--o{ BULK_RESCHEDULE_ITEM : "to move"
    ORGANIZATION ||--o{ COURT_CALENDAR_ENTRY : "non-sitting days"

    HEARING_PURPOSE {
        UUID id PK
        string code UK "never renamed"
        string label
        string description
        int sequence "dropdown order"
        bool is_active "retired, never deleted"
    }
    HEARING {
        UUID id PK
        UUID case FK "PROTECT"
        UUID court FK "Organization; PROTECT"
        UUID purpose FK "HearingPurpose; PROTECT"
        date hearing_date "IST"
        int sequence "board serial no; NULL while provisional/released"
        string status "PROVISIONAL, SCHEDULED, IN_PROGRESS, ..."
        int status_order "derived from status"
        string mode "IN_PERSON, VIDEO, HYBRID"
        date original_date "first fixed date"
        int reschedule_count
        UUID previous_hearing FK "self; PROTECT"
        UUID moves_hearing FK "self; PROTECT"
        UUID source_order_id "order that fixed/holds the date (plain id)"
        UUID order_id UK "order passed in this hearing (plain id)"
        datetime confirmed_at
        datetime started_at
        datetime last_started_at
        datetime ended_at
        duration heard_duration
        datetime abandoned_at
        string adjournment_sought_by "COMPLAINANT, ACCUSED, COURT"
        datetime attendance_locked_at
        datetime cancelled_at
        string cancellation_reason
        string release_reason
    }
    HEARING_ATTENDANCE {
        UUID id PK
        UUID hearing FK "CASCADE"
        string attendee_type "UK with hearing, participant_id"
        UUID participant_id "party on the roll (plain id)"
        string mark "PRESENT, ABSENT, NOT_REQUIRED"
        string appearance_mode "only with PRESENT"
    }
    HEARING_DATE_CHANGE {
        UUID id PK "append-only"
        UUID hearing FK "PROTECT"
        date from_date
        date to_date
        UUID from_purpose FK "PROTECT"
        UUID to_purpose FK "PROTECT"
        string reason_code
        string reason_text
        string sought_by
        string source "COURT_ADMIN, ORDER, BULK"
        UUID source_ref "order id or bulk job id (plain id)"
    }
    BULK_RESCHEDULE_JOB {
        UUID id PK
        UUID court FK "Organization; PROTECT"
        string mode "TO_DATE, NEXT_AVAILABLE"
        date target_date
        date schedule_after
        bool block_source_dates
        string reason_code "court-side reasons only"
        string reason_text
        string status "PREVIEWED ... COMPLETED"
        datetime preview_expires_at
        datetime confirmed_at
        UUID confirmed_by FK "User; PROTECT"
    }
    BULK_RESCHEDULE_ITEM {
        UUID id PK
        UUID job FK "CASCADE; UK with hearing"
        UUID hearing FK "PROTECT; UK with job"
        datetime hearing_updated_at "optimistic-lock snapshot"
        date from_date
        date to_date
        string result "PENDING, MOVED, FAILED, SKIPPED"
        string error_code "only when FAILED"
    }
    COURT_CALENDAR_ENTRY {
        UUID id PK
        UUID court FK "Organization; PROTECT. UK with date"
        date date "UK with court"
        string entry_type "HOLIDAY, REDUCED_SITTING, ..."
        string reason
        int capacity_override "only for REDUCED_SITTING"
    }
```

## 6. Payments — `payments` (spec 0017, 0032)

The shape that matters: `Payment → PaymentDemandItem → DemandItem`. Money rows
are immutable once written; balances are rewritten only by the balance service.
`Demand.case` is the only FK into a domain app; everything else is a plain id.

```mermaid
erDiagram
    CASE ||--o{ DEMAND : "claims on"
    DEMAND ||--o{ DEMAND_ITEM : "charges"
    DEMAND ||--o{ PAYMENT : "collection attempts"
    PAYMENT ||--o{ PAYMENT_DEMAND_ITEM : "allocations"
    DEMAND_ITEM ||--o{ PAYMENT_DEMAND_ITEM : "paid by"
    PAYMENT ||..o{ PAYMENT_ATTESTATION : "provider + provider_payment_id (logical)"

    DEMAND {
        UUID id PK
        string demand_number UK "DMD-..."
        UUID case FK "cases.Case; PROTECT"
        string reference_type
        string reference_id
        UUID organization_id "plain id"
        UUID user_id "party directed to pay (plain id)"
        string currency "INR"
        string status "RAISED, PARTIALLY_PAID, PAID, CANCELLED"
        decimal total_amount "18,2"
        decimal paid_amount
        decimal due_amount
        datetime due_date
        datetime cancelled_at
        string cancellation_reason
    }
    DEMAND_ITEM {
        UUID id PK "cancelled, never deleted"
        UUID demand FK "PROTECT"
        int position
        string charge_type
        string reference_type
        string reference_id
        string description "snapshot at raise time"
        decimal quantity
        decimal unit_amount
        decimal amount
        string account_head
        decimal paid_amount
        decimal due_amount
        string status "UNPAID, PAID, CANCELLED"
        datetime cancelled_at
        string cancellation_reason
    }
    PAYMENT {
        UUID id PK "never deleted; frozen on SUCCESS"
        string payment_number UK "PAY-..."
        UUID demand FK "PROTECT"
        UUID batch_id "shared by a cross-demand checkout"
        decimal amount
        string currency
        string status "INITIATED, PENDING, SUCCESS, FAILED, CANCELLED"
        string payment_mode
        string provider
        string provider_payment_id
        string provider_reference
        string client_request_id "UK with demand (idempotency)"
        json payer
        bool needs_reconciliation
        datetime initiated_at
        datetime completed_at
        datetime failed_at
        datetime cancelled_at
        string failure_code
        string failure_message
        datetime last_polled_at
        int poll_count
    }
    PAYMENT_DEMAND_ITEM {
        UUID id PK "write-once"
        UUID payment FK "PROTECT; UK with demand_item"
        UUID demand_item FK "PROTECT; UK with payment"
        decimal amount "always the full item amount"
    }
    PAYMENT_ATTESTATION {
        UUID id PK "staff-recorded collection; immutable"
        string provider "UK with receipt_number and provider_payment_id"
        string provider_payment_id "UK with provider"
        string receipt_number "UK with provider"
        decimal amount
        string currency
        string method
        json details
        datetime collected_at
        string remarks
        string outcome
    }
    PAYMENT_SEQUENCE {
        UUID id PK
        string prefix "UK with year: DMD-, PAY-"
        int year
        int value
    }
```

## 7. Scrutiny — `scrutiny` (spec 0024)

A case enters a scrutiny or registration **round**; officers raise **flags**
(defects) on it; the filer answers with **responses**. Unresolved flags carry
over to the next round.

```mermaid
erDiagram
    CASE ||--o{ SCRUTINY_ROUND : "rounds"
    USER ||--o{ SCRUTINY_ROUND : "started_by / decided_by"
    SCRUTINY_ROUND ||--o{ SCRUTINY_FLAG : "flags"
    SCRUTINY_FLAG ||--o{ SCRUTINY_FLAG : "auto_marked_by (date chain)"
    SCRUTINY_FLAG ||--o{ SCRUTINY_FLAG : "linked_flag (field to doc issue)"
    SCRUTINY_FLAG ||--o{ SCRUTINY_FLAG : "carried_from (previous round)"
    SCRUTINY_FLAG ||--o{ SCRUTINY_FLAG_RESPONSE : "responses"
    USER ||--o{ SCRUTINY_FLAG : "resolved_by"
    USER ||--o{ SCRUTINY_FLAG_RESPONSE : "responded_by"
    ORGANIZATION ||--o{ SCRUTINY_RULE_BINDING : "jurisdiction"
    BUSINESS_RULE ||..o{ SCRUTINY_RULE_BINDING : "rule_code (by code, no FK)"

    SCRUTINY_ROUND {
        UUID id PK
        UUID case FK "PROTECT; one open round per case"
        string stage "scrutiny, registration"
        int number "UK(case, stage, number); from 1"
        UUID visit_id UK "workflow visit; idempotent open"
        UUID establishment_id "court establishment (plain id)"
        string routing_reason
        UUID courtroom_id "chosen at Forward/Register (plain id)"
        string registration_type
        UUID started_by FK "PROTECT"
        datetime started_at
        string decision "empty while open"
        UUID decided_by FK "PROTECT"
        datetime decided_at
        bool open_items_acknowledged
        int open_items_at_decision
        string comment "registration send-back only"
    }
    SCRUTINY_FLAG {
        UUID id PK
        UUID round FK "CASCADE"
        string target_type "FIELD, SECTION, DOCUMENT, OATH"
        string target_ref "one live flag per target per round"
        string target_label "snapshot for history"
        string section_id "empty for OATH"
        string reason_code "document flags only"
        string note
        json value_at_flag "field flags only"
        UUID auto_marked_by FK "self; CASCADE"
        UUID linked_flag FK "self; SET_NULL"
        UUID carried_from FK "self; PROTECT"
        string status
        UUID resolved_by FK "PROTECT"
        datetime resolved_at
    }
    SCRUTINY_FLAG_RESPONSE {
        UUID id PK
        UUID flag FK "CASCADE"
        string kind "CORRECTED, REUPLOADED, EXPLAINED"
        string note
        json value_after "corrections only"
        UUID document_id "re-uploads only (plain id)"
        UUID responded_by FK "PROTECT"
        datetime responded_at
    }
    SCRUTINY_RULE_BINDING {
        UUID id PK
        string decision "one active binding per decision+org"
        UUID organization FK "PROTECT; NULL = national default"
        string rule_code "BusinessRule.code"
        string note
        bool is_active
    }
```

## 8. Requests & approvals — `dristi_requests` (spec 0010)

Domain-agnostic approval workflow: any request type, configurable steps, side
effects applied by post-approval hooks in the consuming app.

```mermaid
erDiagram
    REQUEST_TYPE ||--o{ APPROVAL_STEP : "step templates"
    AUTH_GROUP ||--o{ APPROVAL_STEP : "approver_group"
    REQUEST_TYPE ||--o{ REQUEST : "instances"
    USER ||--o{ REQUEST : "requester"
    REQUEST ||--o{ REQUEST_DOCUMENT : "attachments"
    FILE ||--o{ REQUEST_DOCUMENT : "content (PROTECT)"
    REQUEST ||--o{ REQUEST_APPROVAL : "approval trail"
    APPROVAL_STEP ||--o{ REQUEST_APPROVAL : "instantiated step (SET_NULL)"
    USER ||--o{ REQUEST_APPROVAL : "approver (SET_NULL)"

    REQUEST_TYPE {
        UUID id PK
        string code UK
        string name
        string description
        json schema "payload schema"
        int min_documents
        bool is_active
    }
    APPROVAL_STEP {
        UUID id PK
        UUID request_type FK "CASCADE; UK with order"
        int order "UK with request_type"
        string approver_role "auth group name"
        UUID approver_group FK "auth.Group; PROTECT"
        json condition "empty = always"
    }
    REQUEST {
        UUID id PK
        string request_number UK "e.g. KL-REQ-00001"
        UUID request_type FK "PROTECT"
        UUID requester FK "User; CASCADE"
        json data
        string status "draft, pending, approved, rejected, cancelled"
        int version "re-submission round"
        int current_step
    }
    REQUEST_DOCUMENT {
        UUID id PK
        UUID request FK "CASCADE"
        UUID file FK "files.File; PROTECT"
    }
    REQUEST_APPROVAL {
        UUID id PK
        UUID request FK "CASCADE; UK with version, step_order"
        UUID step FK "ApprovalStep; SET_NULL"
        int step_order
        int version
        UUID approver FK "User; SET_NULL"
        string status "pending, approved, rejected, skipped"
        string comments
        datetime decided_at
    }
    REQUEST_NUMBER_SEQUENCE {
        UUID id PK
        string prefix UK
        int value
    }
```

## 9. eSign — `esign` (spec 0015)

One row per signing attempt; a retry is a new row linked by `retry_of`, never
a mutation. File references are plain ids owned by `apps.files`.

```mermaid
erDiagram
    USER ||--o{ ESIGN_TRANSACTION : "signer (PROTECT)"
    ESIGN_TRANSACTION ||--o{ ESIGN_TRANSACTION : "retry_of (SET_NULL)"
    FILE ||..o{ ESIGN_TRANSACTION : "source/placeholder/signed file ids (logical)"

    ESIGN_TRANSACTION {
        UUID id PK
        UUID signer FK "User; PROTECT"
        UUID retry_of FK "self; SET_NULL"
        UUID organization_id "plain id"
        string module
        string entity_type
        string entity_id "plain id"
        string provider "UK with provider_transaction_id"
        string provider_transaction_id "UK with provider"
        string source_file_id "plain id"
        string placeholder_file_id "plain id"
        string signed_file_id "plain id"
        json sign_placeholder "x, y, width, height, page"
        string document_hash "hex"
        string signature_field_name
        string status "PENDING, SIGNING, SUCCESS, FAILURE, EXPIRED"
        int attempt_count
        json request_audit
        json response_audit
        string failure_code
        string failure_message
        datetime expires_at
        datetime callback_received_at
        datetime completed_at
    }
```

## 10. PDF generation — `pdf` (spec 0016)

```mermaid
erDiagram
    PDF_TEMPLATE ||--o{ PDF_TEMPLATE_VERSION : "immutable versions"
    PDF_TEMPLATE_VERSION ||--o{ PDF_JOB : "used by (PROTECT)"
    ORGANIZATION ||--o{ PDF_JOB : "tenant org (SET_NULL)"
    USER ||--o{ PDF_JOB : "requested_by (owner, SET_NULL)"
    PDF_JOB ||--o{ PDF_JOB_RECORD : "bulk chunks"
    FILE ||..o{ PDF_JOB : "file_ids / file_id (logical)"

    PDF_TEMPLATE {
        UUID id PK
        string key UK "e.g. case-summons"
        string name
        string description
        bool is_active
    }
    PDF_TEMPLATE_VERSION {
        UUID id PK
        UUID template FK "CASCADE; UK with version"
        int version "auto-assigned; one active per template"
        json format_config
        json data_config
        bool is_active
    }
    PDF_JOB {
        UUID id PK
        string key "template key requested"
        UUID template_version FK "PROTECT"
        string tenant_id
        string entity_id
        UUID organization FK "SET_NULL"
        UUID requested_by FK "owner; SET_NULL"
        string locale
        string correlation_id
        string status "CREATED ... CANCELLED"
        bool is_bulk
        string reuse_key "idempotent reuse"
        json request_data "no auth headers stored"
        json file_ids "generated files"
        int total_count
        int completed_count
        int failed_count
        int attempt_count
        string error_code
        string error_message
        datetime queued_at
        datetime started_at
        datetime completed_at
        datetime files_deleted_at
    }
    PDF_JOB_RECORD {
        UUID id PK
        UUID job FK "CASCADE; UK with sequence"
        int sequence
        int offset
        int count
        string status
        string file_id "plain id"
        int attempt_count
        string error_code
        string error_message
    }
```

## 11. Messaging, notifications & CMS — `messaging`, `notifications`, `cms`

```mermaid
erDiagram
    MESSAGE_TEMPLATE ||--o{ MESSAGE_LOG : "used by (SET_NULL)"
    USER ||--o{ NOTIFICATION : "recipient (CASCADE)"
    PAGE }o--o{ PAGE_CATEGORY : "categories (M2M)"

    MESSAGE_TEMPLATE {
        UUID id PK
        string message_key "UK with message_type"
        string message_type "UK with message_key: email, sms, push"
        string subject "required for email"
        string content
        json data_schema "JSON Schema for context"
        string priority
        string category "OTP, NOTIFICATION, TRANSACTION"
        int max_retries
        string provider_template_id
        bool is_active
    }
    MESSAGE_LOG {
        UUID id PK
        UUID template FK "SET_NULL"
        string message_type
        string message_key
        json recipient
        json context
        string rendered_subject
        string rendered_content
        string status "pending, sent, failed, cancelled, filtered"
        int attempt_count
        int max_retries
        string provider_message_id
        string correlation_id
        string provider
        string error_message
        datetime sent_at
        datetime failed_at
        json provider_metadata
    }
    NOTIFICATION {
        UUID id PK
        UUID recipient FK "User; CASCADE"
        string event_type "upper snake"
        string title
        string body
        json data
        string priority "HIGH, NORMAL, LOW"
        datetime read_at "NULL = unread"
    }
    PAGE {
        UUID id PK
        string slug UK "lowercased on save"
        string title
        string sub_title
        string main_image_url
        string content_type "markdown"
        string content
    }
    PAGE_CATEGORY {
        UUID id PK
        string name UK
        string slug UK
    }
```

## Entity index

| App | Entities |
|---|---|
| `users` | User, LitigantProfile, PowerOfAttorneyProfile, AdvocateProfile, ClerkProfile |
| `parties` | Person, Institution |
| `address` | Address |
| `organizations` | Organization |
| `locations` | Location |
| `files` | File, FileTag |
| `core` | Language, Configuration, PublicConfiguration, BusinessRule, AdditionalAttribute, ApiVersionChangeLog |
| `cases` | Case, CaseParticipant, Witness, PoaMandate, Representation, CaseContact, CaseDocument, CaseEvidence, ChequeBounceCase, ComplaintSigningPackage, CaseNumberSeries |
| `hearings` | HearingPurpose, Hearing, HearingAttendance, HearingDateChange, BulkRescheduleJob, BulkRescheduleItem, CourtCalendarEntry |
| `payments` | Demand, DemandItem, Payment, PaymentDemandItem, PaymentAttestation, PaymentSequence |
| `scrutiny` | ScrutinyRound, ScrutinyFlag, ScrutinyFlagResponse, ScrutinyRuleBinding |
| `dristi_requests` | RequestType, ApprovalStep, Request, RequestDocument, RequestApproval, RequestNumberSequence |
| `esign` | ESignTransaction |
| `pdf` | PDFTemplate, PDFTemplateVersion, PDFJob, PDFJobRecord |
| `messaging` | MessageTemplate, MessageLog |
| `notifications` | Notification |
| `cms` | Page, PageCategory |
