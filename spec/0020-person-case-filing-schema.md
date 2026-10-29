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
| `residential_address_id` | uuid | FK → address, NULLABLE | Current residential address |
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
The current schema permits duplicate persons with the same name and no phone number. Matching logic is implemented at the application layer, and is deliberately narrow:
- The only `person` a party write reuses is the **filer's own**: when the filer adds themselves (`"self": true`, spec 0021 §4.1), their `person` is fetched by `user_id`, or created from their account at `VERIFIED` if they have none yet. A client never sends another person's id, so a filer cannot attach, or read back, someone else's record.
- Every other party gets a **new** row at `ASSERTED`, with no attempt to match by name or phone.
- An existing `person` row is never changed by a party write; the case keeps its own values in the participant snapshot (§4.4).
- Duplicate asserted records resolve when the person registers and claims their row (a separate flow, not part of case filing).

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
| `pan` | varchar(10) | NULLABLE, UNIQUE | Permanent Account Number, e.g. `AAACA1234A`; uppercase, `^[A-Z]{5}[0-9]{4}[A-Z]$` |
| `cin` | varchar(21) | NULLABLE, UNIQUE | Corporate Identification Number, companies only, e.g. `U72200KA2010PTC052651`; uppercase, `^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$` |
| `address_id` | uuid | FK → address, NULLABLE, ON DELETE PROTECT | Registered office: where notices to the institution are served |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel (spec 0002) |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel (spec 0002) |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel (spec 0002) |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel (spec 0002) |

**Constraints:**
- `CHECK (entity_type IN (...))` — values from §3.3
- `CHECK` on the `pan` and `cin` patterns when not null; both are stored uppercase with spaces removed
- `UNIQUE (pan)` and `UNIQUE (cin)` where not null
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

**Why `pan` and `cin`, and how they are matched:**
They identify an entity better than its spelled name, so they are how an institution is reused rather than duplicated. Every company, firm, trust and society has a PAN; only companies have a CIN, so they are two optional columns rather than one, and a company with both is still one row. When a party write names an institution with a PAN or CIN matching an existing row, that row is linked instead of a new one being created:
- The existing row's stored details (name, contact, address) are **not** returned: they may have been entered by another filer, possibly the other side.
- The existing row is not changed. The participant snapshot uses the name sent in this request (§4.4), even if it differs from the stored name, since the PAN or CIN is the better identifier.
- With no PAN or CIN, a new institution is always created.

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

One person's (or institution's) involvement in one case, in one role. Complainants, accused, witnesses and POA holders all have a row here; role-specific data that needs its own columns lives in a table of its own (the `witness` table, §4.5; POA mandates, §5; advocate representation, §6). This table freezes participant data at filing time, while the `person` table remains current.

### 4.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL, ON DELETE CASCADE | |
| `person_id` | uuid | FK → person, NULLABLE | The individual party, or the person acting for an institution |
| `institution_id` | uuid | FK → institution, NULLABLE | The institution party; COMPLAINANT and ACCUSED only |
| `role` | varchar(32) | NOT NULL | COMPLAINANT, ACCUSED, WITNESS, POA_HOLDER |
| `ordinal` | smallint | NOT NULL | 1, 2, 3… per role (complainant #1, accused #2) |
| `name_at_filing` | varchar(256) | NOT NULL | Frozen snapshot of name: the person's, or the institution's when there is no person; 256 wide, as `person.name` and `institution.entity_name`, so any stored name fits |
| `phone_number_at_filing` | varchar(20) | NULLABLE | Frozen snapshot of phone; 20 wide so an institution's landline fits |
| `gender_at_filing` | varchar(32) | NULLABLE | Frozen snapshot of gender |
| `age_at_filing` | smallint | NULLABLE | Frozen snapshot of age: from `person.date_of_birth` when known, else `person.age` |
| `designation_at_filing` | varchar(128) | NULLABLE | The acting person's designation at the institution, e.g. Director; required for an ACCUSED when both `person_id` and `institution_id` are set, optional for a COMPLAINANT |
| `address_id` | uuid | FK → address, NULLABLE | The address for service of notice; required for every role except WITNESS |
| `additional_details` | jsonb | NOT NULL, default '{}' | Role-specific data (see §4.3) |
| `start_date` | timestamp | NOT NULL, default now() | When participant was added |
| `end_date` | timestamp | NULLABLE | When participant was removed |
| `is_party_in_person` | boolean | NOT NULL, default false | Appearing without an advocate |
| `has_signed` | boolean | NOT NULL, default false | True once they have e-signed, or uploaded a signed copy of, the case filing |
| `signature_document_id` | uuid | FK → file, nullable, ON DELETE PROTECT | The signed filing the e-sign service stored (spec 0021 §8). When it was signed is recorded on that e-sign transaction (`completed_at`), not repeated here |
| `is_active` | boolean | NOT NULL, default true | Soft delete flag (spec 0006) |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

Date of birth is optional when filing: a party may be added with only an approximate age, or with neither.

**What the combinations of `person_id` and `institution_id` mean:**

| `person_id` | `institution_id` | Meaning |
|---|---|---|
| set | NULL | An individual party |
| NULL | set | An institution party, with no one named to act for it yet |
| set | set | An institution party and the person acting for it (its director, CEO or authorised signatory); `designation_at_filing` is required for an accused |

**Constraints:**
- `CHECK (person_id IS NOT NULL OR institution_id IS NOT NULL)` — at least one must be set; both may be
- `CHECK (institution_id IS NULL OR role IN ('COMPLAINANT', 'ACCUSED'))` — witnesses and POA holders are always individuals
- `CHECK (person_id IS NULL OR institution_id IS NULL OR role <> 'ACCUSED' OR designation_at_filing IS NOT NULL)` — an accused institution's officer is liable only through their role (for example a director under section 141 of the Negotiable Instruments Act), so the role is recorded; a complainant institution's representative needs authorisation to act, not a title, so a designation is optional there
- `CHECK (role IN ('COMPLAINANT', 'ACCUSED', 'WITNESS', 'POA_HOLDER'))`
- `UNIQUE (case_id, role, ordinal)` WHERE `is_active = true` — each active ordinal is unique per role per case; removed rows keep their old ordinal
- Index on `(case_id, role, is_active)` — common query pattern

**Application-layer rules:**
- The same person cannot be both a complainant and an accused on one case, nor hold the same role twice on it (while active). A complainant may also be the POA holder for a co-complainant (§5).
- `address_id` is required for COMPLAINANT, ACCUSED and POA_HOLDER: notices and summons must be served somewhere.

### 4.3 Role-Specific `additional_details`

The `additional_details` JSONB column stores data that varies by role and has no column of its own. Witness data has its own table (§4.5).

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

**What the snapshot is, and why data is frozen (`name_at_filing`, etc.):**
The `*_at_filing` columns are a frozen copy of the party's details as they stand for this case. Court records must not change with people: if a summons went to a phone number in January and the person changes it in June, the case must still show the January number. The `person` row holds current data; `case_participant` holds the case's copy, and a party write never changes the `person` row (§2.5). Editing a participant edits only its snapshot.

**How a party's person is resolved:**
- The filer adding themselves (`"self": true`): their own `person`, created from their account at `VERIFIED` the first time. Not allowed for an accused.
- Anyone else: a new `person` at `ASSERTED`.
- An institution: matched by `pan` or `cin` when given, otherwise created (§3.4).
- The `person`, institution, address and `case_participant` rows of one party write are created in one transaction: all of them are saved, or none.

**Where the address comes from:**
The request's address is the address for service of notice. It goes through the address service, so an identical address reuses its row (§7.4), and is stored in `address_id`. A newly created `person` also gets it as their `correspondence_address`; an existing `person`'s addresses are left unchanged. District and state are not looked up from the pincode when saving: the client pre-fills them from the pincode lookup endpoint, so a slow or unavailable India Post API never blocks adding a party. When the filer adds themselves without an address, the case address is taken from their profile, once profiles carry one.

**Why both `person_id` and `institution_id`:**
A participant can be a natural person, a legal entity, or both: when an individual files on behalf of a company, `institution_id` points to the company and `person_id` to the individual, whose role there is recorded in `designation_at_filing`. When the filer is that individual (`"self": true` with an institution), the designation is recorded only in the snapshot; the filer's own `person` row is not changed.

**Why `age_at_filing` is computed, and when:**
A stored age goes stale. `age_at_filing` is computed when the participant is added and on each edit: from the date of birth when it is known, else the stated age. When submission is built, it will be recomputed on the filing date.

**Why `ordinal` is separate from `role`, and how it is kept gap-free:**
"All accused" and "accused #2" are both queryable without parsing a combined field. The ordinal resets per role: complainant #1, complainant #2, accused #1, accused #2. While the case is a draft, removing a participant renumbers the remaining active participants of that role to 1…n, so the cause title never reads "Accused No. 1, 3 and 4". Uniqueness applies to active rows only, so a removed row keeps its old ordinal without blocking anyone. Everything that refers to a participant (a representation, a mandate, a linked document) uses its id, never its ordinal, so renumbering breaks no link. After submission writes are refused, so ordinals are fixed; history keeps every earlier value.

**What removing a participant does:**
Removal is a soft delete (`is_active = false`, `end_date = now()`). It also ends the participant's active representations (§6) and the mandates in which they are the represented party (§5); removing a POA holder ends their mandates. Witnesses are not tied to a party (§4.5), so removing a party leaves them in place.

### 4.5 Witnesses: The `witness` Table

#### 4.5.1 Purpose

Witness-specific data, one row per witness. Every witness is also a `case_participant` (role `WITNESS`), which holds their ordinal, snapshot and address; this table adds what only a witness has. Like `cheque_bounce_case` for `cases`, its primary key is the participant's id, so the relationship is strictly one to one.

#### 4.5.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `case_participant_id` | uuid | PK, FK → case_participant, ON DELETE CASCADE | The witness's participant row (role = 'WITNESS') |
| `side` | varchar(16) | NOT NULL, CHECK in (`COMPLAINANT`, `ACCUSED`) | Whose witness: the complainant's or the accused's. The case is the witness participant's `case_id` |
| `what_will_witness_prove` | text | NOT NULL | What the witness's evidence will establish |
| `additional_details` | jsonb | NOT NULL, default '{}' | Anything else about the witness |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Application-layer rules:**
- `case_participant_id` must have `role = 'WITNESS'`.
- While active, a person cannot be a witness twice for the same side of a case.

#### 4.5.3 Design Decisions

**Why a separate table:**
`side` and `what_will_witness_prove` apply only to witnesses. As columns on `case_participant` they would be empty for every other role; in `additional_details` they could not be a checked or required field. A table of their own keeps both enforced by the database.

**Why `side`, not the calling party:**
A witness is called by a side of the case, not by one complainant or accused. Recording the side is what the filing forms ask, and it does not tie the witness to a party who may later be removed or renumbered. A witness re-called by the other side is a new participant with its own `witness` row and the other side. A witness may also have a designation (their job title), kept as `case_participant.designation_at_filing`.

## 5. Power of Attorney: The `poa_mandate` Table

### 5.1 Purpose

Records the authority one participant holds to act for another. A POA holder may act for some parties on a case and not others, so this is a separate table, not a column on `case_participant`.

### 5.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL | Denormalized for query performance |
| `poa_participant_id` | uuid | FK → case_participant, NOT NULL | The POA holder (role = 'POA_HOLDER') |
| `represented_participant_id` | uuid | FK → case_participant, NOT NULL | The party being represented: a COMPLAINANT or ACCUSED |
| `is_active` | boolean | NOT NULL, default true | Active until revoked |
| `granted_at` | timestamp | NOT NULL, default now() | When mandate was granted |
| `revoked_at` | timestamp | NULLABLE | When mandate was revoked |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Constraints:**
- `CHECK (poa_participant_id != represented_participant_id)` — cannot represent oneself
- `UNIQUE (poa_participant_id, represented_participant_id)` WHERE `is_active = true` — one active mandate per holder and party
- Index on `(case_id, is_active)`

**Application-layer rules:**
- `poa_participant_id` must have `role = 'POA_HOLDER'`; `represented_participant_id` must be an active COMPLAINANT or ACCUSED on the same case.
- The holder's person must not be the represented participant's person: a person cannot hold a mandate for themselves under another role.
- Revoking a holder's last active mandate also ends the holder's participant row: a POA holder with no one to act for is no longer a party.

### 5.3 Design Decisions

**Why `case_id` is denormalized:**
Derivable via `poa_participant_id → case_participant → case_id`, but kept so "all POAs on this case" needs no join. This is a read-heavy query pattern.

**Why `is_active` instead of deleting:**
POA history is part of the case record. Who had authority when is material to service of notice and procedural compliance.

**Why no document column:**
The signed POA document is uploaded as a case document of type `POA_DOCUMENT` (§9.3), not linked to a mandate. The filing UI collects signed documents only when the full set of case documents is downloaded and uploaded back, so there is no step at which a document can be tied to one particular mandate. A `document_id` will be added here when documents can be matched to mandates (for example by reading them with OCR).

## 6. Advocate Representation: The `representation` Table

### 6.1 Purpose

Tracks which advocate represents which party in which case. Many-to-many relationship because one advocate can represent multiple parties, and a party can change advocates.

### 6.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL | Denormalized for query performance |
| `advocate_id` | uuid | FK → advocate_profile (spec 0005), NOT NULL | The representing advocate; must be ACCEPTED |
| `case_participant_id` | uuid | FK → case_participant, NOT NULL | The client: a COMPLAINANT or ACCUSED |
| `is_active` | boolean | NOT NULL, default true | Active until advocate withdraws |
| `from_date` | timestamp | NOT NULL, default now() | When representation began |
| `to_date` | timestamp | NULLABLE | When representation ended |
| `created_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `updated_by` | uuid | FK → app_user, NULLABLE | From BaseModel |
| `created_at` | timestamp | NOT NULL, auto | From BaseModel |
| `updated_at` | timestamp | NOT NULL, auto | From BaseModel |

**Constraints:**
- `UNIQUE (advocate_id, case_participant_id)` WHERE `is_active = true` — the same advocate cannot represent the same client twice at once
- Index on `(case_id, is_active)` — "all active advocates on this case"
- Index on `(advocate_id, is_active)` — "all active cases for this advocate"
- Index on `(case_participant_id, is_active)` — "who represents this party"

**Application-layer rules:**
- `advocate_id` must be an `AdvocateProfile` with `approval_status = ACCEPTED`; PENDING and REJECTED advocates cannot represent anyone.
- The client must be an active COMPLAINANT or ACCUSED on the same case.
- No self-representation: the advocate's user must not be the client person's user. A party appearing for themselves is marked `is_party_in_person` instead.
- A client marked `is_party_in_person = true` cannot be given an advocate; the request is rejected.
- A client may have several active advocates (for example a senior and a junior advocate).
- An advocate cannot act for both sides: while active, the same advocate cannot represent a complainant and an accused on one case.

### 6.3 Design Decisions

**Why three rows for three clients:**
If advocate A represents complainants #1, #2, and #3, that's three `representation` rows with the same `advocate_id`. This keeps queries simple: "who does advocate A represent" is just `WHERE advocate_id = A`.

**Why `is_active` and `to_date` coexist:**
`is_active = false` is a soft delete for administrative removal. `to_date` is the historical record of when representation ended. An advocate who withdrew has `to_date` set and `is_active = false`; one who was administratively removed has only `is_active = false`.

**Why `case_id` is denormalized:**
Same reason as `poa_mandate`: "all advocates on this case" is a common query and should not require joining through `case_participant`.

**Why no vakalatnama column:**
As for POA documents (§5.3), the signed vakalatnama is uploaded as a case document of type `VAKALATNAMA` (§9.3). It cannot yet be tied to one advocate's representation, so a `vakalatnama_document_id` will be added when documents can be matched to representations.

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
| `police_station` | varchar(255) | NOT NULL, may be blank | Police station with jurisdiction over the address, needed for service of notice. Required for accused and witness addresses; complainant and POA holder addresses may leave it blank |
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
Pincodes are stored as `pincode` locations under their district (spec
[`0007`](0007-location.md)), so no third-party API is called. At entry time the
client calls `GET /api/v1/locations/code/PIN_{pincode}/ancestors/?is_active=true`,
which returns the country, state and district, and pre-fills `district` and
`state` from it; the values are then stored on the address. This denormalizes
the data but makes queries faster. A `404` means the pincode is not loaded or
is deactivated, and the user enters district and state by hand.

The earlier India Post lookup (`GET /api/v1/pincodes/{pincode}/`) is removed.

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

Case statuses and their transitions are not hardcoded. They are driven by the
workflow configuration in [0011 — Case Workflows](0011-case-workflows.md)
(`WorkflowDefinition` / `WorkflowState` / `WorkflowTransition` per
`case_type`), with the case's current state held by `CaseWorkflowInstance`.
`cases.status` is a projection of that state, written only by the workflow
engine (0011 §3.3); the §138 lifecycle is 0011 §10.

**Why `created_by` is NOT NULL:**
Every case has a filer. System-created cases (migrations, imports) should use a dedicated system user (see spec 0002, §5).

**Why `court_id` is nullable:**
Drafts may not have a court assigned yet. Could be tightened with a constraint: `CHECK (status != 'FILED' OR court_id IS NOT NULL)`.

## 9. Case Documents: The `case_document` Table

### 9.1 Purpose

Documents filed as part of the case itself. A classification layer over the document store (spec 0014). A document belongs to the case, and may also say whose it is (`case_participant_id`) or which evidence item it supports (`case_evidence_id`).

### 9.2 Schema

| Field | Type | Constraints | Notes |
|-------|------|-------------|-------|
| `id` | uuid | PK | |
| `case_id` | uuid | FK → cases, NOT NULL, ON DELETE CASCADE | |
| `document_id` | uuid | FK → document, NOT NULL, ON DELETE PROTECT | From file storage service (spec 0014) |
| `document_type` | varchar(64) | NOT NULL | See §9.3 |
| `case_participant_id` | uuid | FK → case_participant, NULLABLE, ON DELETE SET NULL | Whose document: an identity proof, vakalatnama or POA document (§9.3) |
| `case_evidence_id` | uuid | FK → case_evidence, NULLABLE, ON DELETE SET NULL | The evidence item it supports: a cheque's scan, a demand notice's dispatch, delivery or reply papers (§9.3) |
| `is_active` | boolean | NOT NULL, default true | Soft delete — documents get replaced during scrutiny |
| `additional_details` | jsonb | NOT NULL, default '{}' | Type-specific metadata; `is_digital` (born digital, not a scan) and `display_name` (the uploader's name for it) when sent |
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
- `PROOF_OF_DELIVERY_OF_DEMAND_NOTICE`
- `REPLY_TO_DEMAND_NOTICE`
- `PROOF_OF_DEBT`
- `AFFIDAVIT`
- `VAKALATNAMA` (when an advocate represents a party)
- `POA_DOCUMENT` (when a POA holder acts for a party)
- `OTHER_SUPPORTING_DOCUMENT`
- `IDENTITY_PROOF` (each complainant's)
- `PROOF_OF_TRANSACTION` (a loan agreement, invoice or ledger behind the debt)

New case types add new enums without altering the table structure.

**Links.** Some types belong to a party or an evidence item, and may be linked to it:

| Document type | `case_participant_id` (role) | `case_evidence_id` (evidence type) |
|---|---|---|
| `IDENTITY_PROOF` | COMPLAINANT | — |
| `VAKALATNAMA`, `POA_DOCUMENT` | COMPLAINANT or ACCUSED (the party represented) | — |
| `BOUNCED_CHEQUE` | — | CHEQUE |
| `RETURN_MEMO` | — | RETURN_MEMO |
| `LEGAL_DEMAND_NOTICE`, `PROOF_OF_DISPATCH`, `PROOF_OF_DELIVERY_OF_DEMAND_NOTICE`, `REPLY_TO_DEMAND_NOTICE` | — | LEGAL_DEMAND_NOTICE |

Any other link is refused (`E07030`), as is a participant of the wrong role (`E07016`) or on another case (`E07010`), and evidence of the wrong type (`E07029`) or on another case (`E07031`). The completeness check counts a per-party or per-notice document only when it is linked (spec 0021 §6.3). A vakalatnama is still linked to the party, not to one `representation`; a POA document to the represented party, not to one `poa_mandate`.

### 9.4 Design Decisions

**Why `document_type` is an enum:**
It drives the upload checklist UI and the completeness gate before preview. An unrecognized value would silently break both, so the set must be closed.

**Why optional links on this table, not separate tables:**
Every document is still a case document, filed and listed with the case. Two nullable foreign keys say whose it is or what it supports, which is enough for the per-complainant and per-notice checks, without a `participant_document` or `evidence_document` table for each kind. `ON DELETE SET NULL`, since participants and evidence are soft-deleted; a hard delete only drops the link.

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

Each JSONB column corresponds to one section of the filing form, stored as it is
displayed. The schemas each section is validated against are in spec 0021 §5.3.

**`jurisdiction_limitation`:**
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

**`adr_other_prayer`:**
```json
{
  "adr_preference": "MAYBE",
  "other_details": "",
  "interim_relief": "<p>Direct the Accused to pay interim compensation under Section 143A ...</p>",
  "final_relief": "<p>Take cognizance of the offence committed by the Accused under Section 138 ...</p>"
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
| `case_document_id` | uuid | FK → case_document, NULLABLE | The evidence's own scan; must be of its type: `BOUNCED_CHEQUE` for a cheque, `RETURN_MEMO`, `LEGAL_DEMAND_NOTICE` (`E07029` otherwise) |
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

The schemas each type is validated against are in spec 0021 §5.2. For cheque
bounce, each cheque has one `RETURN_MEMO` and one `LEGAL_DEMAND_NOTICE`,
matched to it by `ordinal`.

**For `evidence_type = 'CHEQUE'`:**
```json
{
  "cheque_date": "2024-01-15",
  "amount": 50000,
  "cheque_number": "456789",
  "ifsc_code": "SBIN0001234",
  "bank_name": "State Bank of India",
  "bank_branch": "MG Road"
}
```

**For `evidence_type = 'RETURN_MEMO'`:**
```json
{
  "presentation_date": "2024-01-18",
  "return_date": "2024-01-22",
  "return_reason": "Funds insufficient"
}
```

**For `evidence_type = 'LEGAL_DEMAND_NOTICE'`:**
```json
{
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
```

### 11.4 Design Decisions

**Why separate from `case_document`:**
`case_document` classifies uploads; `case_evidence` structures the legal evidence with metadata. A cheque scan is both a document (classification) and evidence (legal artifact with amount, date, bank). Keeping them separate follows single responsibility.

**Why `ordinal`:**
Supports multiple instances of the same evidence type. "Cheque #1" and "Cheque #2" are queryable, sortable, and displayable in order.

**When to promote `evidence_info` fields to columns:**
If queries filter by amount (`WHERE evidence_info->>'amount' > 100000`), promote `amount` to a real `numeric(15,2)` column with an index. Same for `cheque_date` if date-range queries are common.

**Why link to `case_document_id`:**
A piece of evidence may have no uploaded file yet (entered as metadata before scanning), so the FK is nullable. When the file is uploaded, link it. The scan must be of the evidence's own type, so a proof of dispatch can never stand in for a cheque. Other papers about the evidence, such as a notice's proof of delivery, point the other way, through `case_document.case_evidence_id` (§9.3).

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
| 1 | An accused is named at filing, has never registered | `person`, `case_participant` | A new `person` with `user_id = NULL`, `verification_level = ASSERTED` |
| 2 | That accused later registers and claims their record | `person`, `users_user` | `person.user_id` set, `verification_level = VERIFIED`. The claim flow is not part of case filing: filing only guarantees the starting state of scenario 1 |
| 3 | A complainant files with OTP verification | `person`, `case_participant`, `users_user` | `person.user_id` set, `verification_level = VERIFIED` |
| 4 | Complainant's witness | `case_participant`, `witness` | `case_participant.role = WITNESS`; `witness.side = COMPLAINANT`, `what_will_witness_prove` set |
| 5 | Power of attorney holder acts for two parties | `poa_mandate` (2 rows) | Same `poa_participant_id`, different `represented_participant_id` |
| 6 | Advocate represents three complainants | `representation` (3 rows) | Same `advocate_id`, different `case_participant_id` |
| 7 | Notice served to a specific address, person later moves | `address` (2 rows), `case_participant.address_id` unchanged | Immutable address preserves service record |
| 8 | Person's phone number changes | `person.phone_number` updated | `case_participant.phone_number_at_filing` unchanged |
| 9 | Multiple cheques in one case | `case_evidence` | `evidence_type = CHEQUE`, `ordinal = 1/2/3` |
| 10 | Case transitions through scrutiny | `cases.status` | DRAFT_IN_PROGRESS → PENDING_SIGN → ... → REGISTERED |
| 11 | Document replaced during scrutiny | `case_document` | Old row: `is_active = false`, new row: `is_active = true` |
| 12 | Institution as complainant, represented by CEO | `case_participant`, `person`, `institution` | `institution_id` set (reused when its PAN or CIN matches), `person_id` set for the CEO, `designation_at_filing` set if given (optional for a complainant). A CEO entered by the filer is a new `person` with `institution_id` and `designation` set; when the filer is the CEO (`self`), their own `person` is unchanged and the designation is only in the snapshot |

## 14. Validation Rules

### 14.1 Application-Layer Checks

- `case_participant`: At least one of `person_id` or `institution_id` must be set; when both are set on an ACCUSED, `designation_at_filing` is required. Only COMPLAINANT and ACCUSED may have an `institution_id`.
- `case_participant`: The same person cannot be a complainant and an accused on one case, nor hold one role twice there while active. `address_id` is required except for witnesses.
- `witness`: an active person is a witness at most once per side of a case.
- `poa_mandate`: The represented participant is an active COMPLAINANT or ACCUSED on the same case, and not the holder's own person.
- `representation`: The client is an active COMPLAINANT or ACCUSED on the same case, not marked `is_party_in_person`, not the advocate themselves, and not on the opposite side from another active client of the same advocate.
- `person.designation`: Only meaningful when `person.institution_id` is set.
- `poa_mandate`: `poa_participant_id` must have `role = 'POA_HOLDER'`.
- `representation`: `advocate_id` must point to an `AdvocateProfile` (spec 0005) with `approval_status = ACCEPTED`.
- `case_evidence.ordinal`: Must be unique per `(case_id, evidence_type)` when `is_active = true`.
- `person.phone_number`: When not null, must be an E.164 number (`+`, country code, number), any country (§2.4).
- `institution.pan` / `institution.cin`: When not null, must match their formats (§3.2).

### 14.2 Database Constraints

Implement via `CHECK` constraints and triggers:
- `person`: `CHECK ((phone_number IS NULL) OR (phone_number ~ '^\+[1-9][0-9]{6,14}$'))`
- `case_participant`: `CHECK (person_id IS NOT NULL OR institution_id IS NOT NULL)`, plus the role and designation checks in §4.2
- `case_participant`: `UNIQUE (case_id, role, ordinal) WHERE is_active`
- `poa_mandate`: `UNIQUE (poa_participant_id, represented_participant_id) WHERE is_active`
- `representation`: `UNIQUE (advocate_id, case_participant_id) WHERE is_active`
- `institution.entity_type`: `CHECK (entity_type IN ('PRIVATE_LIMITED_COMPANY', 'PUBLIC_LIMITED_COMPANY', 'LLP', ...))`
- `address.pincode`: `CHECK (pincode ~ '^[1-9][0-9]{5}$')`
- `cases.status`: `CHECK (status IN ('DRAFT_IN_PROGRESS', 'PENDING_SIGN', ...))`

## 15. References

- **Spec 0002**: BaseModel audit fields
- **Spec 0005**: User model and registration
- **Spec 0006**: Active flag pattern for soft deletes
- **Spec 0008**: Organization model
- **Spec 0014**: File storage service for document management
- **All India Pincode Directory** (source for `import_pincodes`): https://www.data.gov.in/catalog/all-india-pincode-directory

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
All tables that are edited during a filing keep a full change history (spec 0004): `person` and `institution` (§3.4), `cases`, `case_document`, `cheque_bounce_case`, `case_evidence`, and `case_participant`, `witness`, `poa_mandate` and `representation`.
