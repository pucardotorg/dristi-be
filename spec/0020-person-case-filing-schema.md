# Person, Case Filing, and Evidence Management Schema

## Status
Proposed

## 1. Goal

Model the complete lifecycle of case filing and participant management, such that:

- Any human can exist in the system before registration (as accused, witness, etc.) and later claim their record.
- Participant data is frozen at filing time while person records remain current.
- Power of attorney relationships, advocate representation, and participant roles are tracked separately and can change over time.
- Case documents and evidence are categorized and linked to cases with type-specific metadata.
- Address records are immutable snapshots to preserve what was served at what address.
- Multiple case types can be supported without altering the core case table.

This spec builds on:
- **0002**: BaseModel for audit fields (`created_by`, `updated_by`, `created_at`, `updated_at`)
- **0004**: Simple Audit History for version tracking and change history
- **0005**: User model for registered accounts
- **0006**: Active flag pattern for soft deletes
- **0008**: Organization model
- **0014**: File storage service for document management

## 2. Core Identity: The `person` Table

### 2.1 Purpose

One row per human being the system knows of, whether registered or not. A person can be a litigant, an accused named in a filing, a witness, a power of attorney holder, or hold multiple roles across different cases.

### 2.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `name` | varchar(256) | NOT NULL | Full name |
| `phone_number` | varchar(16) | NULLABLE | E.164 (`+`, country code, number, digits only), any country; a blank value is stored as NULL |
| `email_address` | varchar(256) | NULLABLE | |
| `relation` | varchar(16) | NULLABLE | Relationship type (S/O, D/O, W/O, etc.) |
| `relative_name` | varchar(256) | NULLABLE | Father's / spouse's / guardian's name; required when `relation` is set |
| `date_of_birth` | date | NULLABLE | Not after today's date in India (IST); `TIME_ZONE` is UTC, so the server's date is not used |
| `age` | smallint | NULLABLE, CHECK 0–150 | Approximate age, only when the date of birth is unknown ("aged about 45"); cleared whenever `date_of_birth` is set |
| `gender` | varchar(32) | NULLABLE | One of: MALE, FEMALE, OTHER, PREFER_NOT_TO_SAY |
| `institution_id` | uuid | FK → institution, NULLABLE | When acting for an institution (see §3) |
| `designation` | varchar(128) | NULLABLE | Role within the institution, e.g. Director, Branch Manager, Authorised Signatory |
| `permanent_address_id` | uuid | FK → address, NULLABLE | Current permanent address |
| `correspondence_address_id` | uuid | FK → address, NULLABLE | Current mailing address |
| `disability_status` | varchar(16) | NOT NULL, default NONE | NONE, VISUAL, HEARING, MOBILITY, COGNITIVE, OTHER; a missing or blank value is stored as NONE |
| `verification_level` | varchar(16) | NOT NULL, default ASSERTED | See §2.3 |
| `user_id` | uuid | FK → app_user, NULLABLE, UNIQUE | NULL until they register |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel (spec 0002) |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel (spec 0002) |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel (spec 0002) |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel (spec 0002) |

### 2.3 Verification Levels

Identity verification is a spectrum. The `verification_level` field records how we know this person is who they claim to be:

| Level | What Happened | Example |
|-------|---------------|---------|
| `ASSERTED` | Someone typed a name into a form. No contact, no proof. | An accused named by the complainant at filing |
| `CONTACTED` | We sent something to a number and it reached them | A surety who opened an SMS link and signed |
| `VERIFIED` | OTP confirmed — they control that number | A complainant who filed, a POA at filing |

### 2.4 Design Decisions

**Why `user_id` is nullable and unique:**
- An accused can exist in the system before they ever register (`user_id = NULL`).
- When they do register, their existing `person` row links to their new `User` record via `user_id`.
- The uniqueness constraint ensures one person cannot claim multiple user accounts.

**Why `phone_number` is nullable:**
- Not every person has a phone number at creation (a minor, an uncontacted party).

**Why `age` alongside `date_of_birth`:**
- The exact date of birth of an accused or witness is often unknown, while the complaint still states an approximate age ("aged about 45"). `age` records that. When the date of birth is known it is the only source of truth: `age` is cleared on save, and today's age is computed from the date of birth (`Person.current_age`, which the API returns as `age`). Storing both would let the stored age go stale at the next birthday and contradict the date of birth. Because any age changes over time, `case_participant.age_at_filing` freezes the age that was true on the filing date (§4).

**Why `disability_status` defaults to `NONE`:**
- Every person has a value, so queries and forms never need to treat a missing status separately. A missing or blank value is stored as `NONE`, and the column also has a database default, so a row inserted outside Django gets it too.

**Why `phone_number` is any E.164 number, not an Indian mobile:**
- A party may live abroad, or be reachable only on a landline. Unlike a `User`'s login number (spec 0005), this number is only for contacting the person, so any country is accepted. The model validator and a `CHECK` constraint use the same pattern, `^\+[1-9][0-9]{6,14}$`.

**Why every save is validated:**
- The rules that need more than one field (a relation needs the relative's name, a designation needs an institution) and the date-of-birth check run in `full_clean()`, which Django calls only from forms. `Person.save()` and `Institution.save()` call it themselves, so a plain `create()` from a service cannot store a record that breaks them. Names are trimmed first, so a whitespace-only name is rejected as missing.

**Why the API does not show who entered a person or institution:**
- Records are often entered by the other side (the complainant's advocate records the accused). `created_by` / `updated_by` stay in the database, the history tables and the admin, but serializers do not expose them.

**Why addresses are FKs, not embedded:**
- Immutability requirement (see §7) — addresses are snapshots, not live fields.
- Multiple persons can share an address without duplication.

**Why `designation` lives on `person`:**
- It describes the person's role at the institution in `institution_id` (for example, the Director who files for a company), so it is only meaningful when `institution_id` is set.
- Like the rest of `person`, it holds current data. If a filing must preserve the designation as it was at filing time, it belongs in the participant snapshot (§4).

### 2.5 Open Questions

**Uniqueness constraints:**
The current schema permits duplicate persons with the same name and no phone number. Matching logic must be implemented at the application layer:
- Match and reuse only when identity is proven (`verification_level = VERIFIED`).
- Otherwise create a new row at `ASSERTED`.
- Duplicate asserted records resolve when the person registers and claims their row.

## 3. Legal Entities: The `institution` Table

### 3.1 Purpose

One row per non-human party the system knows of: a company, LLP, partnership firm, proprietorship, society or trust, and so on. An institution can be a complainant or an accused in a case, and acts through people (`person.institution_id` with a `designation`).

### 3.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `entity_type` | varchar(32) | NOT NULL | See §3.3 |
| `entity_name` | varchar(256) | NOT NULL | Registered / legal name |
| `contact_number` | varchar(20) | NULLABLE | Main contact number; may be a landline. Digits only, optionally grouped with parentheses, spaces or hyphens, with an optional leading `+`; a blank value is stored as NULL |
| `email_address` | varchar(256) | NULLABLE | Main contact email |
| `address_id` | uuid | FK → address, NULLABLE, ON DELETE PROTECT | Registered office: where notices to the institution are served |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel (spec 0002) |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel (spec 0002) |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel (spec 0002) |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel (spec 0002) |

**Constraints:**
- `CHECK (entity_type IN (...))` — values from §3.3
- Index on `entity_name` — lookup when naming a party at filing

### 3.3 Entity Types (enum)

Initial set, to be confirmed:

| Value | Meaning |
|-------|---------|
| `PRIVATE_LIMITED_COMPANY` | Company limited by shares whose shares are not offered to the public (e.g. "ABC Pvt Ltd") |
| `PUBLIC_LIMITED_COMPANY` | Company limited by shares whose shares may be offered to the public, listed or unlisted (e.g. "ABC Ltd") |
| `LLP` | Limited liability partnership registered under the LLP Act, 2008 |
| `PARTNERSHIP_FIRM` | Registered or unregistered partnership firm |
| `PROPRIETORSHIP` | Sole proprietorship trading under a business name |
| `SOCIETY_TRUST` | Registered society, cooperative society, or public/private trust |
| `OTHER_ENTITY` | Any legal entity not covered above (e.g. government department, local body, bank) |

### 3.4 Design Decisions

**Why an institution has its own address:**
A company or firm named as a party is served at its registered office, which need not be the address of whoever signs for it, so it is recorded on the institution rather than reached through a linked person. Like every address, it is an immutable row (§7): a move is a new row and the FK is repointed.

**Why `institution` and `person` keep full history:**
Both are edited over the life of a case (a party's name or number is corrected, a company renamed), and a court record must show what the record said when a notice went out. Both use `BaseAuditableModel` (spec 0004): every insert, update and delete is copied to `parties_historicalperson` / `parties_historicalinstitution` with who made it and when. `address` needs no history table: it is immutable, so every past version is still its own row.

**Why a separate table instead of `organization` (spec 0008):**
`Organization` models the court hierarchy: its `OrganizationType` holds only court types, and it carries a parent chain and jurisdictions. Litigant entities share none of that. Keeping them separate means a court can never be recorded as a party by mistake, and each table only has the fields it needs.

**Why `contact_number` is not validated as a mobile number:**
Unlike `person.phone_number`, an institution's number is often a landline or a toll-free line, so the Indian mobile pattern from spec 0005 does not apply. It is still restricted to digits and grouping characters (`+`, parentheses, spaces, hyphens), by a model validator and a `CHECK` constraint, so letters such as `080-CALL-NOW` are rejected.

## 4. Case Participation: The `case_participant` Table

### 4.1 Purpose

One person's (or institution's) involvement in one case, in one role. This table freezes participant data at filing time, while the `person` table remains current.

### 4.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL, ON DELETE CASCADE | |
| `person_id` | uuid | FK → person, NULLABLE | NULL when participant is an institution |
| `institution_id` | uuid | FK → institution, NULLABLE | NULL when participant is a person |
| `role` | varchar(32) | NOT NULL | COMPLAINANT, ACCUSED, WITNESS, POA_HOLDER |
| `ordinal` | smallint | NOT NULL | 1, 2, 3… (complainant #1, accused #2) |
| `name_at_filing` | varchar(256) | NOT NULL | Frozen snapshot of name |
| `phone_number_at_filing` | varchar(16) | NULLABLE | Frozen snapshot of phone |
| `gender_at_filing` | varchar(32) | NULLABLE | Frozen snapshot of gender |
| `age_at_filing` | smallint | NULLABLE | Frozen snapshot of age when filed: computed from `person.date_of_birth` on the filing date when known, else `person.age` |
| `address_id` | uuid | FK → address, NULLABLE | The address for service of notice |
| `called_by_participant_id` | uuid | FK → case_participant, NULLABLE | For witnesses: which party called them |
| `additional_details` | jsonb | NOT NULL, default '{}' | Role-specific data (see §4.3) |
| `start_date` | timestamp | NOT NULL, default now() | When participant was added |
| `end_date` | timestamp | NULLABLE | When participant was removed |
| `is_party_in_person` | boolean | NOT NULL, default false | Appearing without an advocate |
| `has_signed` | boolean | NOT NULL, default false | Value for this while be 'true' if they have e-signed or has uploaded a signed copy of the case filing |
| `is_active` | boolean | NOT NULL, default true | Soft delete flag (spec 0006) |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Constraints:**
- `CHECK (person_id IS NOT NULL OR institution_id IS NOT NULL)` — at least one must be set
- `CHECK (person_id IS NULL OR institution_id IS NULL)` — but not both
- `UNIQUE (case_id, role, ordinal)` — each ordinal is unique per role per case
- Index on `(case_id, role, is_active)` — common query pattern

### 4.3 Role-Specific `additional_details`

The `additional_details` JSONB column can store data that varies by role:

**For `WITNESS`:**
```json
{
  "what_will_witness_prove": "Eyewitness to the transaction on 2024-01-15"
}
```

**For `ACCUSED`:**
```json
{
  "previous_convictions": false,
  "bail_status": "granted"
}
```

**For `POA_HOLDER`:**
```json
{
  "scope": "Limited to this case only",
  "relationship_to_principal": "Business partner"
}
```

### 4.4 Design Decisions

**Why freeze data at filing (`name_at_filing`, etc.):**
Court records must not change with people. If notice was served to an address in January, the case file must show that exact address forever. The `person` row holds current data; `case_participant` holds the filing snapshot.

**Why both `person_id` and `institution_id`:**
A participant can be either a natural person or a legal entity. When an individual files on behalf of a company, both are set: `person_id` points to the individual, `institution_id` to the company.

**Why `ordinal` is separate from `role`:**
"All accused" and "accused #2" are both queryable without parsing a combined field. The ordinal resets per role: complainant #1, complainant #2, accused #1, accused #2.

**Why `called_by_participant_id` for witnesses:**
Tracks which party called this witness, creating a clear evidence chain. A witness can be re-called by the opposing party in a new row with a different `called_by_participant_id`.

## 5. Power of Attorney: The `poa_mandate` Table

### 5.1 Purpose

Records the authority one participant holds to act for another. A POA holder may act for some parties on a case and not others, so this is a separate table, not a column on `case_participant`.

### 5.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL | Denormalized for query performance |
| `poa_participant_id` | uuid | FK → case_participant, NOT NULL | The POA holder (role = 'POA_HOLDER') |
| `represented_participant_id` | uuid | FK → case_participant, NOT NULL | The party being represented |
| `poa_type` | varchar(64) | NULLABLE | Scope/category of authority |
| `document_id` | uuid | FK → document, NULLABLE | The signed authorization |
| `is_active` | boolean | NOT NULL, default true | Active until revoked |
| `granted_at` | timestamp | NOT NULL, default now() | When mandate was granted |
| `revoked_at` | timestamp | NULLABLE | When mandate was revoked |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Constraints:**
- `CHECK (poa_participant_id != represented_participant_id)` — cannot represent oneself
- `UNIQUE (poa_participant_id, represented_participant_id, case_id, granted_at)` when `is_active = true`
- Index on `(case_id, is_active)`
- FK constraint ensures `poa_participant_id` has `role = 'POA_HOLDER'` (enforced via trigger or app validation)

### 5.3 Design Decisions

**Why `case_id` is denormalized:**
Derivable via `poa_participant_id → case_participant → case_id`, but kept so "all POAs on this case" needs no join. This is a read-heavy query pattern.

**Why `is_active` instead of deleting:**
POA history is part of the case record. Who had authority when is material to service of notice and procedural compliance.

## 6. Advocate Representation: The `representation` Table

### 6.1 Purpose

Tracks which advocate represents which party in which case. Many-to-many relationship because one advocate can represent multiple parties, and a party can change advocates.

### 6.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL | Denormalized for query performance |
| `advocate_id` | uuid | FK → advocate_profile (spec 0005), NOT NULL | The representing advocate |
| `case_participant_id` | uuid | FK → case_participant, NOT NULL | The client |
| `vakalatnama_document_id` | uuid | FK → document, NULLABLE | The signed authorization |
| `is_active` | boolean | NOT NULL, default true | Active until advocate withdraws |
| `from_date` | timestamp | NOT NULL, default now() | When representation began |
| `to_date` | timestamp | NULLABLE | When representation ended |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Constraints:**
- Index on `(case_id, is_active)` — "all active advocates on this case"
- Index on `(advocate_id, is_active)` — "all active cases for this advocate"
- Index on `(case_participant_id, is_active)` — "who represents this party"

### 6.3 Design Decisions

**Why three rows for three clients:**
If advocate A represents complainants #1, #2, and #3, that's three `representation` rows with the same `advocate_id`. This keeps queries simple: "who does advocate A represent" is just `WHERE advocate_id = A`.

**Why `is_active` and `to_date` coexist:**
`is_active = false` is a soft delete for administrative removal. `to_date` is the historical record of when representation ended. An advocate who withdrew has `to_date` set and `is_active = false`; one who was administratively removed has only `is_active = false`.

**Why `case_id` is denormalized:**
Same reason as `poa_mandate`: "all advocates on this case" is a common query and should not require joining through `case_participant`.

## 7. Immutable Addresses: The `address` Table

### 7.1 Purpose

A single recorded address. Rows are **immutable snapshots**: once written, never updated. A new address means a new row.

### 7.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `line1` | varchar(255) | NOT NULL | Street address / locality |
| `city` | varchar(100) | NOT NULL | City or town |
| `pincode` | varchar(6) | NOT NULL | Indian postal code |
| `district` | varchar(100) | NOT NULL | Auto-filled from pincode, then stored |
| `state` | varchar(100) | NOT NULL | Auto-filled from pincode, then stored |
| `police_station` | varchar(255) | NOT NULL | Police station with jurisdiction over the address, needed for service of notice |
| `hash` | varchar(64) | NOT NULL, UNIQUE | SHA-256 of the canonical form, see §7.4 |
| `created_at` | timestamp | NOT NULL, default now() | Creation timestamp only, no `updated_at` |
| `created_by` | uuid | FK → app_user, NULLABLE, ON DELETE PROTECT | Who first recorded the address; no `updated_by` |

**Constraints:**
- `CHECK (pincode ~ '^[1-9][0-9]{5}$')` — 6 digits, not starting with 0
- `UNIQUE (hash)` — one row per distinct address
- `CHECK (hash ~ '^[0-9a-f]{64}$')` — a row written without its hash is refused
- Index on `pincode` for geolocation queries

### 7.3 Design Decisions

**Why immutable:**
Court records require stable addresses. If notice was served to 123 Main St in January, the case file must forever show that address, even if the person has since moved. Editing an address creates a new row and repoints the FK.

**Why `address` does not inherit `BaseModel`:**
Spec 0000 makes `BaseModel` the default, but its audit fields do not fit an immutable row: `updated_at` and `updated_by` would never change, and its `created_by` is `ON DELETE SET_NULL`, which would rewrite the row when a user is deleted. `Address` declares its own UUID `id`, `created_at` and a `PROTECT` `created_by` instead, and orders newest first like `BaseModel`.

**Why auto-fill district and state:**
Use the [India Post Pincode API](https://api.postalpincode.in/pincode/{pincode}) to populate district and state at entry time, then store them. This denormalizes the data but makes queries faster and survives API unavailability.

**Why no `updated_at` or `updated_by`:**
Rows are never updated. The absence of these fields, and of BaseModel itself, is intentional — it signals immutability to future maintainers.

**Why `created_by` is `ON DELETE PROTECT`:**
`SET_NULL` would rewrite existing rows when a user is deleted, breaking immutability. A user who recorded an address is deactivated rather than deleted.

**How immutability is enforced:**
`Address.save()` inserts only and raises `AddressImmutableError` on an existing row; `Address.delete()` always raises. To change an address, call `address.revise(created_by=user, **changes)`, which returns the row holding the new values, and repoint the FK at it. The admin allows adding and viewing only. Bulk `QuerySet.update()` / `.delete()` and raw SQL bypass these checks; a database trigger rejecting `UPDATE` and `DELETE` would close that gap if needed. `bulk_create()` also skips `save()`, so the manager overrides it to normalize and hash each row itself; the `CHECK` on `hash` refuses any other insert that arrives without one.

### 7.4 Deduplication Strategy

Two addresses with identical content reuse the same row. Create addresses through the manager rather than `Address.objects.create`:

```python
address, created = Address.objects.get_or_create_address(
    created_by=request.user,
    line1=line1,
    city=city,
    pincode=pincode,
    district=district,
    state=state,
    police_station=police_station,
)
```

**Canonical form:** each content field (`line1`, `city`, `state`, `pincode`, `district`, `police_station`) is put in Unicode NFC form, cleared of invisible characters (zero-width space U+200B, word joiner U+2060, byte-order mark U+FEFF), trimmed, and has inner whitespace collapsed to one space; `pincode` keeps no spaces (`"560 001"` → `"560001"`). Values are stored in this form with their original case.

NFC matters for Indian scripts: the same visible Malayalam or Hindi text can arrive as different code points depending on the keyboard or input method (`"क़"` precomposed, or `"क"` plus a nukta), and without it they would be stored as different addresses. The zero-width joiner and non-joiner (U+200D, U+200C) are kept, because Malayalam and Devanagari use them to choose how letters join.

**Hash:** SHA-256 of the canonical fields joined by a unit separator (`\x1f`), stored in `hash` with a unique index. Only whitespace is normalized: `"12  MG Road"` and `"12 MG Road"` are the same address, but `"12 mg road"` is a different one. Case is significant on purpose. If it were ignored, whoever typed an address first would fix its casing for everyone after, and a case-only correction (`revise(city="Bengaluru")` on a row stored as `"bengaluru"`) could never be saved, so badly cased addresses would be printed on notices. `save()` always recomputes the hash, so a stored hash always matches the stored values.

**Behaviour:**
- An existing match is returned as is, keeping its original `created_by`. `created_by` is not part of the hash, so two users recording the same address share one row.
- Because one row can be shared by unrelated parties (a complainant and an accused at the same place), `created_by` only says who entered it first, not who owns it. The API does not expose it; it is kept for audit in the database and admin.
- A case-only change is a different address, so `revise()` creates a new row for it and leaves the original untouched.
- `revise()` goes through the same path, so revising to an address that already exists returns that row, and a revision with no changes returns the original.
- Concurrent callers are safe: the unique index makes the losing insert fall back to the existing row.
- A direct duplicate insert fails at the unique index; model validation (and so the admin add form) reports "This address already exists." instead.

## 8. Core Case Record: The `cases` Table

### 8.1 Purpose

One filing. Holds only what every dispute type shares; type-specific data goes in its own table (e.g., `cheque_bounce_case`).

### 8.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_type` | varchar(32) | NOT NULL | CHEQUE_BOUNCE for now; says which detail table to join |
| `filing_number` | varchar(64) | UNIQUE, NULLABLE | Generated at submission, NULL while draft |
| `case_number` | varchar(64) | UNIQUE, NULLABLE | Court-assigned at registration |
| `cnr_number` | varchar(64) | UNIQUE, NULLABLE | National case number |
| `status` | varchar(32) | NOT NULL | See §8.3 |
| `court_id` | varchar(64) | NULLABLE | FK to court master data |
| `filed_at` | timestamp | NULLABLE | When submission completed, NULL while draft |
| `registered_at` | timestamp | NULLABLE | When court accepted the case |
| `created_by` | uuid | FK → app_user, NOT NULL | The filer (from BaseModel) |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Indexes:**
- `(status, created_by)` — "my drafts", "my pending cases"
- `(filing_number)` — unique constraint also serves as index
- `(case_type, status)` — case type queries

### 8.3 Case Status Lifecycle

**TODO:** Case statuses and their transitions are not meant to be hardcoded.
They will be driven by the workflow configuration in
0011 — Case Workflows(0011-case-workflows.md) `WorkflowDefinition` /
`WorkflowState` / `WorkflowTransition` per `case_type`, with the case's
current state held by `CaseWorkflowInstance`. The table below describes the
expected e-filing lifecycle for the first case type and is illustrative
until that integration is specified.

**Why three identifiers (`filing_number`, `case_number`, `cnr_number`):**
- `filing_number`: System-generated at submission, stable throughout.
- `case_number`: Court-assigned at registration, the public identifier.
- `cnr_number`: National identifier for inter-court tracking.

**Why `created_by` is NOT NULL:**
Every case has a filer. System-created cases (migrations, imports) should use a dedicated system user (see spec 0002, §5).

**Why `court_id` is nullable:**
Drafts may not have a court assigned yet. Could be tightened with a constraint: `CHECK (status != 'FILED' OR court_id IS NOT NULL)`.

## 9. Case Documents: The `case_document` Table

### 9.1 Purpose

Documents filed as part of the case itself. A classification layer over the document store (spec 0014), holding only case-level documents rather than party-specific or relationship-specific ones.

### 9.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL, ON DELETE CASCADE | |
| `document_id` | uuid | FK → document, NOT NULL, ON DELETE PROTECT | From file storage service (spec 0014) |
| `document_type` | varchar(64) | NOT NULL | See §9.3 |
| `is_active` | boolean | NOT NULL, default true | Soft delete — documents get replaced during scrutiny |
| `additional_details` | jsonb | NOT NULL, default '{}' | Type-specific metadata |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Constraints:**
- `UNIQUE (case_id, document_id)` — the same file can't be filed twice under one case
- Index on `(case_id, document_type, is_active)` — "show me this case's active return memos"

### 9.3 Document Types (enum)

The `document_type` field drives upload checklists and completeness gates:

**For cheque bounce cases:**
- `BOUNCED_CHEQUE`
- `RETURN_MEMO`
- `LEGAL_DEMAND_NOTICE`
- `PROOF_OF_DISPATCH`
- `PROOF_OF_DEBT`
- `AFFIDAVIT`
- `VAKALATNAMA` (when advocate represents)
- `POA_DOCUMENT` (when POA holder represents)
- `OTHER_SUPPORTING_DOCUMENT`

New case types add new enums without altering the table structure.

### 9.4 Design Decisions

**Why `document_type` is an enum:**
It drives the upload checklist UI and the completeness gate before preview. An unrecognized value would silently break both, so the set must be closed.

**Why only case-level documents:**
Party-specific documents (e.g., a witness's affidavit) would require adding a `case_participant_id` FK, which couples document classification to participant structure. Keep case-level documents here; consider a separate `participant_document` table if needed.

**Why `ON DELETE PROTECT` on `document_id`:**
Deleting the underlying file should not cascade to case records. If a document must be removed from the case, set `is_active = false`.

## 10. Cheque Bounce Cases: The `cheque_bounce_case` Table

### 10.1 Purpose

Cheque-bounce-specific data. One row per case, with `case_id` as both PK and FK to enforce a strict 1:1 relationship with `cases`.

### 10.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK, FK → cases, ON DELETE CASCADE | |
| `jurisdiction_limitation` | jsonb | NOT NULL, default '{}' | Section 3 of e-filing form |
| `adr_other_prayer` | jsonb | NOT NULL, default '{}' | Section 4 of e-filing form |
| `additional_details` | jsonb | NOT NULL, default '{}' | Anything else not promoted to columns |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

### 10.3 JSONB Structure

Each JSONB column corresponds to one section of the filing form, stored as it is displayed:

**`jurisdiction_limitation`:**
```json
{
  "jurisdiction_grounds": "Cheque dishonored within territorial jurisdiction",
  "limitation_compliance": true,
  "limitation_notes": "Demand notice sent within 30 days of dishonor"
}
```

**`adr_other_prayer`:**
```json
{
  "adr_attempted": true,
  "adr_method": "Mediation",
  "adr_outcome": "Failed",
  "prayers": [
    "Recovery of cheque amount",
    "Interest at 18% per annum",
    "Costs of litigation"
  ]
}
```

### 10.4 Design Decisions

**Why one JSONB column per UI section:**
Data is stored the way it is read back. Fetching "Section 3" data means reading one JSONB column, not reassembling it from scattered fields.

**Why `case_id` is the PK:**
Enforces 1:1 with `cases`. No separate `cheque_bounce_case_id`; the case ID is the identifier.

**When to promote fields to columns:**
If a field drives frequent queries or filtering (e.g., "all cases where limitation is non-compliant"), promote it from JSONB to a real column with an index. Start with JSONB for flexibility; promote as query patterns emerge.

## 11. Case Evidence: The `case_evidence` Table

### 11.1 Purpose

Evidence attached to a case: the cheque, return memo, demand notice, postal acknowledgment, affidavits, and other supporting material. Type-specific details are stored in JSONB; frequently queried fields may later be promoted to columns.

### 11.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL, ON DELETE CASCADE | |
| `case_document_id` | uuid | FK → case_document, NULLABLE | Links to the uploaded file |
| `evidence_type` | varchar(64) | NOT NULL | CHEQUE, RETURN_MEMO, LEGAL_DEMAND_NOTICE, etc. |
| `ordinal` | smallint | NOT NULL | Cheque #1, cheque #2, demand notice #1 |
| `evidence_info` | jsonb | NOT NULL, default '{}' | Type-specific details, see §11.3 |
| `is_active` | boolean | NOT NULL, default true | Soft delete |
| `additional_details` | jsonb | NOT NULL, default '{}' | Future extensibility |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Constraints:**
- `UNIQUE (case_id, evidence_type, ordinal, is_active)` WHERE `is_active = true`
- Index on `(case_id, evidence_type, is_active)`

### 11.3 Evidence Info Structure by Type

**For `evidence_type = 'CHEQUE'`:**
```json
{
  "cheque_number": "456789",
  "bank_account_number": "1234567890",
  "drawee_bank": "State Bank of India",
  "amount": 50000.00,
  "cheque_date": "2024-01-15",
  "return_memo_date": "2024-01-22"
}
```

**For `evidence_type = 'RETURN_MEMO'`:**
```json
{
  "return_reason": "Insufficient funds",
  "return_date": "2024-01-22",
  "bank_name": "State Bank of India"
}
```

**For `evidence_type = 'LEGAL_DEMAND_NOTICE'`:**
```json
{
  "notice_date": "2024-02-01",
  "dispatch_date": "2024-02-01",
  "dispatch_method": "Registered post",
  "tracking_number": "RR123456789IN"
}
```

### 11.4 Design Decisions

**Why separate from `case_document`:**
`case_document` classifies uploads; `case_evidence` structures the legal evidence with metadata. A cheque scan is both a document (classification) and evidence (legal artifact with amount, date, bank). Keeping them separate follows single responsibility.

**Why `ordinal`:**
Supports multiple instances of the same evidence type. "Cheque #1" and "Cheque #2" are queryable, sortable, and displayable in order.

**When to promote `evidence_info` fields to columns:**
If queries filter by amount (`WHERE evidence_info->>'amount' > 100000`), promote `amount` to a real `numeric(15,2)` column with an index. Same for `cheque_date` if date-range queries are common.

**Why link to `case_document_id`:**
A piece of evidence may have no uploaded file yet (entered as metadata before scanning), so the FK is nullable. When the file is uploaded, link it.

## 12. Migration Path

### 12.1 Existing User Model

This spec assumes spec 0005's `User` model is already in place:
- `mobile_number` as `USERNAME_FIELD`
- Role field: `LITIGANT`, `POWER_OF_ATTORNEY`, `ADVOCATE`, `CLERK`
- Profile tables: `AdvocateProfile`, `ClerkProfile`, `LitigantProfile`, `PowerOfAttorneyProfile`

The `person.user_id` FK points to this existing model.

### 12.2 Backfill Strategy

**Not shipped:** no deployment holds real user data yet, so no backfill
migration exists. Litigants get a `person` row as the filing flow creates
them. The steps below apply only if `person` is introduced to a deployment that
already has registered users.

When introducing `person` to an existing deployment with registered users:

1. Create all new tables with FKs nullable.
2. For each `User` where `role = LITIGANT`:
   ```sql
   INSERT INTO person (person_id, name, phone_number, user_id, verification_level, ...)
   SELECT gen_random_uuid(), u.name, u.mobile_number, u.id, 'VERIFIED', ...
   FROM users_user u
   WHERE u.role = 'LITIGANT';
   ```
3. For advocates and clerks, their professional profiles already exist — link via `user_id` but do not duplicate into `person` unless they are also parties to a case.

### 12.3 Adding New Case Types

To add a second case type (e.g., civil suit):

1. Define a new `civil_suit_case` table with `case_id` as PK/FK.
2. Add `'CIVIL_SUIT'` to the `case_type` enum.
3. Define new `document_type` and `evidence_type` values for that case type.
4. No changes to core tables (`cases`, `case_participant`, `representation`, etc.).

## 13. Scenarios Covered

| # | Scenario | Tables Involved | Key Fields |
|---|----------|-----------------|------------|
| 1 | An accused is named at filing, has never registered | `person`, `case_participant` | `person.user_id = NULL`, `verification_level = ASSERTED` |
| 2 | That accused later registers and claims their record | `person`, `users_user` | `person.user_id` set, `verification_level = VERIFIED` |
| 3 | A complainant files with OTP verification | `person`, `case_participant`, `users_user` | `person.user_id` set, `verification_level = VERIFIED` |
| 4 | Witness called by complainant #1 | `case_participant` | `role = WITNESS`, `called_by_participant_id → complainant` |
| 5 | Power of attorney holder acts for two parties | `poa_mandate` (2 rows) | Same `poa_participant_id`, different `represented_participant_id` |
| 6 | Advocate represents three complainants | `representation` (3 rows) | Same `advocate_id`, different `case_participant_id` |
| 7 | Notice served to a specific address, person later moves | `address` (2 rows), `case_participant.address_id` unchanged | Immutable address preserves service record |
| 8 | Person's phone number changes | `person.phone_number` updated | `case_participant.phone_number_at_filing` unchanged |
| 9 | Multiple cheques in one case | `case_evidence` | `evidence_type = CHEQUE`, `ordinal = 1/2/3` |
| 10 | Case transitions through scrutiny | `cases.status` | DRAFT_IN_PROGRESS → PENDING_SIGN → ... → REGISTERED |
| 11 | Document replaced during scrutiny | `case_document` | Old row: `is_active = false`, new row: `is_active = true` |
| 12 | Institution as complainant, represented by CEO | `case_participant`, `person` | `institution_id` set, `person_id` set for CEO; CEO's `person.institution_id` and `designation` set |

## 14. Validation Rules

### 14.1 Application-Layer Checks

- `case_participant`: Exactly one of `person_id` or `institution_id` must be set.
- `person.designation`: Only meaningful when `person.institution_id` is set.
- `poa_mandate`: `poa_participant_id` must have `role = 'POA_HOLDER'`.
- `representation`: `advocate_id` must point to a valid `AdvocateProfile` (spec 0005).
- `case_evidence.ordinal`: Must be unique per `(case_id, evidence_type)` when `is_active = true`.
- `person.phone_number`: When not null, must match Indian mobile pattern (spec 0005).

### 14.2 Database Constraints

Implement via `CHECK` constraints and triggers:
- `person`: `CHECK ((phone_number IS NULL) OR (phone_number ~ '^\+91[6-9]\d{9}$'))`
- `case_participant`: `CHECK ((person_id IS NOT NULL)::int + (institution_id IS NOT NULL)::int = 1)`
- `institution.entity_type`: `CHECK (entity_type IN ('PRIVATE_LIMITED_COMPANY', 'PUBLIC_LIMITED_COMPANY', 'LLP', ...))`
- `address.pincode`: `CHECK (pincode ~ '^[1-9][0-9]{5}$')`
- `cases.status`: `CHECK (status IN ('DRAFT_IN_PROGRESS', 'PENDING_SIGN', ...))`

## 15. References

- **Spec 0002**: BaseModel audit fields
- **Spec 0005**: User model and registration
- **Spec 0006**: Active flag pattern for soft deletes
- **Spec 0008**: Organization model
- **Spec 0014**: File storage service for document management
- **India Post Pincode API**: https://api.postalpincode.in/pincode/{pincode}

## 16. Future Enhancements

### 16.1 Separate Witness Table
If witness-specific data grows (testimony dates, cross-examination notes), extract to:
```sql
CREATE TABLE witness (
  witness_id uuid PRIMARY KEY,
  case_participant_id uuid REFERENCES case_participant,
  what_will_prove text,
  testimony_date date,
  ...
);
```

### 16.2 Evidence Versioning
Track amendments to evidence records:
```sql
ALTER TABLE case_evidence ADD COLUMN version smallint DEFAULT 1;
ALTER TABLE case_evidence ADD COLUMN supersedes_evidence_id uuid REFERENCES case_evidence;
```

### 16.3 Audit History Integration
Apply spec 0004 (Simple Audit History) to track who changed what when on `cases`, `case_participant`, and `representation` tables. `person` and `institution` already do (§3.4).
