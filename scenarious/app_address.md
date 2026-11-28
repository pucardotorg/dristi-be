# Address scenarios

Scenario IDs for the immutable-address integration tests (spec 0020 §7,
marked per spec 0037 §15). Each table row maps to a test tagged
`@pytest.mark.scenario("<ID>-<#>")` — row 2 of `ADDR-DEDUP` is
`ADDR-DEDUP-2`. IDs are assigned manually; once a test carries one it is
never renumbered or reused.

```bash
cd src
pytest --scenario ADDR-DEDUP-2                            # run one scenario
pytest apps/address --scenario-report scenario-map.json   # regenerate the ID → test map
```

`apps.address` exposes **no REST API of its own**: its real surfaces are the
manager entry points (`get_or_create_address`, `revise`), the admin, and the
`AddressSerializer` other apps nest (spec 0037 §1 shapes 2–3). Per-branch
unit coverage lives in `apps/address/tests/test_models.py`; the tables below
pin the dedup/immutability contracts other apps rely on, and the admin
surface an operator can reach.

Addresses are created the way the product creates them — through
`Address.objects.get_or_create_address`, never `Address.objects.create`
(spec 0037 §3): the manager is what normalizes, hashes and deduplicates.

## Deduplication — one row per distinct address

ID: ADDR-DEDUP
Endpoints: `Address.objects.get_or_create_address` (spec 0020 §7.4)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | an address recorded with `line1="12  MG Road "` | the same address is recorded as `"12 MG Road"` | the same row comes back (`created=False`) — surrounding whitespace is dropped and inner runs collapse before hashing |
| 2 | an address whose `line1` holds Malayalam text in precomposed NFC form | the same visible text arrives decomposed (base letters + combining marks) | the same row — NFC normalization makes input methods indistinguishable |
| 3 | an address with `pincode="560 001"` | it is recorded | the stored row holds `560001` — a pincode keeps no spaces at all |
| 4 | an address with `city="Bengaluru"` | the same address is recorded with `city="bengaluru"` | a **second** row — case is significant on purpose, or a case-only correction could never be saved |
| 5 | an address recorded by user A | user B records the identical address | one shared row keeping A's `created_by` — the field says who entered it first, not who owns it, and the serializer never exposes it |
| 6 | — | every field blank (or only invisible/zero-width characters) | `ValidationError` — an address with every field blank is refused |
| 7 | an address recorded with only `pincode` | it is read back | stored with the other fields blank; `missing_fields` returns `["line1", "city", "state", "district"]` in postal order — partial addresses are valid while a filing is drafted |
| 8 | an address with a zero-width space / word joiner / BOM pasted into `line1` | it is recorded | the stored value is cleaned of invisible characters — but a zero-width joiner/non-joiner inside Malayalam text is **kept** (they choose how letters join) |

Tests: `apps/address/tests/integration/test_dedup_flow.py`.

## Immutability and revision

ID: ADDR-IMMUTABLE
Endpoints: `Address.save` · `Address.delete` · `Address.revise` (spec 0020 §7.3)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a recorded address | a field is changed on the instance and `save()` is called | `AddressImmutableError`; `refresh_from_db` shows the row untouched |
| 2 | a recorded address | `delete()` is called | `AddressImmutableError`; the row and its `hash` remain |
| 3 | a recorded address | `revise(city="Mysuru", created_by=user)` | a **new** row holding the revised values; the original is unchanged — a case file forever shows the address as it was when used |
| 4 | a recorded address, and a second address equal to the intended revision | `revise(...)` toward the second's values, then `revise()` with no changes | the first call returns the existing second row (dedup on revision); the no-change call returns the original row itself |
| 5 | two concurrent callers | both record the same new address at once | one row, one winner — the unique `hash` index makes the losing insert fall back to the existing row |
| 6 | a recorded address | `Address.objects.bulk_create([...])` with new addresses | each row is normalized and hashed by the manager override — `bulk_create` skips `save()`, and a row without its hash would never deduplicate (the DB `CHECK` refuses it) |

Tests: `apps/address/tests/integration/test_immutability_flow.py`.

## Pincode pre-fill — what the address stores

ID: ADDR-PINCODE
Endpoints: `GET /api/v1/locations/code/{code}/ancestors/` → `get_or_create_address` (spec 0020 §7.3, spec 0007 §7)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | the seeded chain `IN` → `IN_KL` → `IN_KL_ERN` → `PIN_682001` (all active) | the client resolves the pincode's ancestors, takes the `district` and `state` entries, and records the address with them | the address row stores district `Ernakulam` and state `Kerala` as sent — the lookup result is denormalized onto the immutable row |
| 2 | the same chain | an address is recorded whose `district`/`state` contradict the pincode's chain | it is stored as sent — district and state are **not** looked up or checked at save time, so a slow or missing location lookup never blocks a party write |
| 3 | no `PIN_999999` location exists (or it is deactivated) | the pincode lookup 404s and the user types district and state by hand | the address is stored with the hand-entered values — a 404 means "no pre-fill", never a block |

Notes:

- The locations side of row 1 (the ancestors call itself, its 404 contract)
  is pinned in `scenarious/app_locations.md` (`LOC-PINCODE`); this table pins
  only what the address module does with the outcome.
- Tests: `apps/address/tests/integration/test_pincode_flow.py`.

## Admin — add and view only

ID: ADDR-ADMIN
Endpoints: `/admin/address/address/` (spec 0020 §7.3; spec 0037 §5)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | — | a superuser adds an address through the admin add form | the row is saved normalized and hashed, with `created_by` stamped by the audit mixin |
| 2 | an existing address | the superuser submits the add form with the same values | the form re-renders with "This address already exists." — model validation, not a 500 from the unique index |
| 3 | an existing address | the superuser opens its change view and POSTs an edit | the change is refused (`has_change_permission` is `False`) and `refresh_from_db` shows the row untouched |
| 4 | an existing address | the superuser attempts delete | refused (`has_delete_permission` is `False`); the row remains |
| 5 | — | the add form is submitted with `pincode="012345"`, then `"12345"` | field error both times — a pincode is 6 digits not starting with 0, or blank |

Tests: `apps/address/tests/integration/test_admin_flow.py`.

## Consumers — how parties use addresses

ID: ADDR-CONSUMERS
Endpoints: party writes in `apps.parties` that carry addresses (spec 0020 §4.6, §7)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | two unrelated party writes (different cases) naming the identical address | both writes complete | both cases' `ADDRESS` contacts point at **one** shared address row — a complainant and an accused at the same place share it, and neither sees who recorded it first |
| 2 | a case whose `ADDRESS` contact references an address | anything attempts to delete the address | the address survives: `Address.delete()` always raises, and the contact's FK is `PROTECT` besides |

Notes:

- The flow tests for these rows live in `apps.parties` — that app owns the
  party-write behavior (spec 0037 §2 rule 1); they are listed here because
  they pin the address module's consumer contract. Row IDs are tagged in the
  parties suite.
- Tests: `apps/parties/tests/integration/` (tagged `ADDR-CONSUMERS-*`).
