# Case–Party Relationship Model — Spec

## 1. Purpose

Models how `Case`s relate to the people and organizations involved in them:
what role each party plays (complainant, accused, witness, judge, etc.),
whether they're appearing individually or on behalf of an organization, who
represents whom (lawyer, clerk, or power of attorney), and whether that
role/representation is currently active.

## 2. Models

### 2.1 `Case`
The case itself. Links to participants only through the two relationship
tables below (`people` / `organizations` are convenience M2M accessors over
them).

| Field | Type | Notes |
|---|---|---|
| `title` | CharField | |
| `people` | M2M → User | through `CasePersonRelationship` |
| `organizations` | M2M → Organization | through `CaseOrganizationRelationship` |

### 2.2 `Role` (enum, shared by both relationship tables)

| Value | DB string | Notes |
|---|---|---|
| Complainant | `complainant` | party bringing the case |
| Accused | `accused` | party the case is against |
| Lawyer | `lawyer` | can represent another party (see `Representation`) |
| Lawyer's Office Clerk | `lawyer_office_clerk` | represents like a lawyer; optionally tied to a supervising lawyer via `LawyerClerkProfile` |
| Power of Attorney | `poa` | represents like a lawyer, but not a legal professional |
| Witness | `witness` | |
| Judge | `judge` | |
| Self-represented (Pro Se) | `self_represented` | party representing themselves — no `Representation` row |

`LAWYER`, `LAWYER_OFFICE_CLERK`, and `POA` are collectively the
**representative roles** (`Representation.REPRESENTATIVE_ROLES`) — the only
roles allowed to stand in a `Representation` row on the representing side.

### 2.3 `Organization`
A company/firm that can itself be a party to a case.

| Field | Type |
|---|---|
| `name` | CharField |

### 2.4 `CaseOrganizationRelationship`
An organization's membership in a case — mirrors `CasePersonRelationship` but
for organizations. This is what makes an org a *party* (e.g. complainant),
not just an entity referenced elsewhere.

| Field | Type | Notes |
|---|---|---|
| `case` | FK → Case | |
| `organization` | FK → Organization | |
| `role` | CharField (`Role`) | |
| `start_date` | DateField, nullable | |
| `end_date` | DateField, nullable | `NULL` = role still active |

- `unique_together`: (`case`, `organization`, `role`)
- `is_active` property: `True` iff `end_date is None`
- `objects`: `ActiveRoleQuerySet` (see §2.7)
- `clean()`: rejects `end_date < start_date`

### 2.5 `CasePersonRelationship`
A user's membership in a case, and in what role. This is the central table.

| Field | Type | Notes |
|---|---|---|
| `case` | FK → Case | |
| `person` | FK → `settings.AUTH_USER_MODEL` | |
| `role` | CharField (`Role`) | |
| `appearing_for` | FK → `CaseOrganizationRelationship`, nullable | set when this person is appearing *as a representative of* an org (e.g. its CEO), not individually |
| `capacity` | CharField, blank | title held when `appearing_for` is set, e.g. `"CEO"`, `"CFO"` |
| `start_date` | DateField, nullable | |
| `end_date` | DateField, nullable | `NULL` = role still active |

- `unique_together`: (`case`, `person`, `role`, `appearing_for`)
- `is_active` property, `objects = ActiveRoleQuerySet.as_manager()` — same as above
- `clean()`:
  - `appearing_for`'s case must match this row's case
  - `capacity` is only valid alongside `appearing_for`
  - rejects `end_date < start_date`

### 2.6 `Representation`
Links a representative (`Role.LAWYER` / `LAWYER_OFFICE_CLERK` / `POA`) to the
party's relationship row they act for.

| Field | Type | Notes |
|---|---|---|
| `representative_relationship` | OneToOne → `CasePersonRelationship` | must have role in `REPRESENTATIVE_ROLES` |
| `represents` | FK → `CasePersonRelationship` | the party being represented |

- `clean()` enforces:
  - `representative_relationship.role` is one of `LAWYER` / `LAWYER_OFFICE_CLERK` / `POA`
  - both rows are on the same case
  - the represented row is *not itself* a representative role (no representing a representative)
  - the representative and the represented party are not the same person (self-representation is `Role.SELF_REPRESENTED`, not a `Representation` row)
- `OneToOneField` on `representative_relationship` means one representative row currently represents exactly one party row. (Relax to `ForeignKey` if a single lawyer/clerk/PoA holder must represent multiple parties on the same case.)

### 2.7 `LawyerProfile` / `LawyerClerkProfile`
Off-case professional metadata — not tied to any specific case, just to the
person. A user only has one of these if they are, in real life, a lawyer or a
clerk.

| Model | Field | Type | Notes |
|---|---|---|---|
| `LawyerProfile` | `person` | OneToOne → User | |
| | `bar_number` | CharField, blank | |
| | `firm` | CharField, blank | |
| `LawyerClerkProfile` | `person` | OneToOne → User | |
| | `employee_id` | CharField, blank | |
| | `firm` | CharField, blank | |
| | `supervising_lawyer` | FK → `LawyerProfile`, nullable, `SET_NULL` | |

### 2.8 `ActiveRoleQuerySet`
Shared queryset mixed into both relationship tables' `objects` manager.

```python
CasePersonRelationship.objects.active()  # end_date IS NULL or in the future
CasePersonRelationship.objects.active(as_of=some_date)  # as of a specific date
CasePersonRelationship.objects.inactive()  # end_date has passed
```

## 3. Known deferred item

`Representation.represents` only points at `CasePersonRelationship`. There's
no way yet to represent a `CaseOrganizationRelationship` directly (e.g. "our
firm represents Acme Corp" with no named individual on Acme's side). Likely
fix: `GenericForeignKey` or a shared abstract base for "representable case
party." Intentionally deferred.

## 4. Scenarios covered

| # | Scenario | Tables involved | Key fields exercised |
|---|---|---|---|
| 1 | Individual complainant | `CasePersonRelationship` | `role=COMPLAINANT` |
| 2 | Complainant represented by a lawyer | `CasePersonRelationship` ×2, `Representation` | `Representation.representative_relationship.role=LAWYER` |
| 3 | Organization as a party (e.g. accused) | `CaseOrganizationRelationship` | `role=ACCUSED` |
| 4 | Person appearing on behalf of an organization, in a capacity | `CasePersonRelationship` | `appearing_for`, `capacity="CEO"` |
| 5 | Lawyer representing that org-appearing person | `CasePersonRelationship` ×2, `Representation` | `represents` → row with `appearing_for` set |
| 6 | Witness | `CasePersonRelationship` | `role=WITNESS` |
| 7 | Judge assigned to a case | `CasePersonRelationship` | `role=JUDGE` |
| 8 | Self-represented (pro se) party | `CasePersonRelationship` | `role=SELF_REPRESENTED`, no `Representation` row |
| 9 | Role that has ended (e.g. lawyer withdrew) | `CasePersonRelationship` | `end_date` set, `is_active=False` |
| 10 | Party represented via Power of Attorney instead of a lawyer | `CasePersonRelationship` ×2, `Representation` | `representative_relationship.role=POA` |
| 11 | Party represented by a lawyer's office clerk | `CasePersonRelationship` ×2, `Representation`, `LawyerClerkProfile` | `role=LAWYER_OFFICE_CLERK`, `supervising_lawyer` |
| 12 | Querying only currently active roles on a case | `CasePersonRelationship` / `CaseOrganizationRelationship` | `ActiveRoleQuerySet.active()` |
| 13 | Querying roles as of a past date | same | `ActiveRoleQuerySet.active(as_of=...)` |

### Scenarios explicitly rejected by validation (`clean()`)

| Attempted scenario | Where it's blocked | Why |
|---|---|---|
| A lawyer representing another lawyer | `Representation.clean()` | represented role can't itself be a representative role |
| A person representing themselves via `Representation` | `Representation.clean()` | must use `Role.SELF_REPRESENTED` instead |
| Representative and represented party on different cases | `Representation.clean()` | both rows must share `case` |
| `capacity` set without `appearing_for` | `CasePersonRelationship.clean()` | capacity only meaningful when appearing for an org |
| `appearing_for` pointing at an org relationship on a different case | `CasePersonRelationship.clean()` | must be a party to the same case |
| `end_date` earlier than `start_date` | both relationship models' `clean()` | date sanity |

### Not yet supported (see §3)

- A firm/lawyer representing an organization's `CaseOrganizationRelationship`
  row with no named individual on the organization's side.
