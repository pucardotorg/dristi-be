# Users scenarios

Scenario IDs for the registration and login tests (spec 0005; spec 0037 §15).
Each table row maps to a test tagged `@pytest.mark.scenario("<ID>-<#>")` —
row 2 of `USER-OTP` is `USER-OTP-2`. IDs are assigned manually; once a test
carries one it is never renumbered or reused.

```bash
cd src
pytest --scenario USER-SESSION-3                        # run one scenario
pytest apps/users --scenario-report scenario-map.json   # regenerate the ID → test map
```

The flows are cookie-based throughout (spec 0005 §1): a client is a logged-in
browser, so every test drives real `APIClient` sessions — one client per actor
(spec 0037 §4.1) — and never re-authenticates a client mid-test.

## OTP requests — issuing codes

ID: USER-OTP
Endpoints: `POST /auth/otp/request/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | no account on `+919876543210` | POST a `register` code request | 202 with the generic "if the number is valid" detail; exactly one SMS enqueued through messaging with the `ACCOUNT_REGISTRATION_OTP_SMS` template; the cache holds only a keyed **digest** of the code, never the code |
| 2 | a code was just sent to a number | POST another request for the same number inside the cooldown | 429 with code `E01005` and a `Retry-After` header (≥ 1 second); no second SMS is sent |
| 3 | a `register` code was just sent to a number | POST a `login` request for the same number inside the cooldown | 429 `E01005` — the cooldown is keyed on the number alone, so alternating purposes buys no second window |
| 4 | the cooldown key has expired (the cache no longer holds it) | POST again for the same number | 202; a fresh code replaces the old one (the old code no longer verifies) |
| 5 | a number with no account | POST a `password_reset` code request | the same 202 body as for a known number — the endpoint reveals nothing about which numbers hold accounts (a code is still "sent") |
| 6 | a malformed mobile number (`9876543210`, `+14155552671`) | POST | 400 with `E00001` on `mobile_number` — the implementation accepts only the Indian `+91[6-9]xxxxxxxxx` form, narrower than spec 0005 §5.2's generic E.164 (current behavior, pinned) |
| 7 | an unknown purpose (`"verify_email"`) | POST | 400 with `E00001` on `purpose` |
| 8 | a code was just sent to a number | five more requests arrive back-to-back (an impatient user hammering "resend") | the first was the only SMS; every repeat is 429 `E01005` with `Retry-After` never below 1 — one write wins the key, the rest are refused (`cache.add()` is the whole mechanism) |
| 9 | no cooldown active | the SMS hand-off to messaging raises mid-request | the request fails, and the number is **not** left cooldown-locked: the cooldown key is removed with the failure, so an immediate retry is 202 — a failed send must not look like a sent one |
| 10 | no accounts at all | requests for three **different** numbers in quick succession | all three are 202 — the cooldown is per number, and there is no per-caller ceiling (current behavior, pinned so introducing one fails a test) |

Notes:

- Tests capture the issued code by patching
  `apps.users.services.otp._send_sms` — the messaging-boundary seam the
  existing unit suite (`apps/users/tests/base.py`) already uses — and keep the
  real `enqueue_sms` for MessageLog assertions where the table asks for them.
- "Cooldown expired" (row 4) is simulated at the cache boundary — the expiry
  *is* the key's absence (spec 0005 §4.1.3) — not by sleeping.
- Row 9 injects the failure at the messaging boundary (`_send_sms` raising),
  the seam spec 0037 §6 prefers; the assertion is on the cooldown key being
  cleaned up, which is what lets the retry through.
- Known consequence pinned, spec 0005 §4.1.3.1: the code reaches the
  `MessageLog` (`context` and rendered content) in plaintext. A test asserts
  this current behavior so its removal fails a test.
- Tests: `apps/users/tests/integration/test_otp_flow.py`.

## Account creation — the OTP is the credential

ID: USER-CREATE
Endpoints: `POST /users/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a `register` code for a number with no account | POST `{mobile_number, otp}` | 201 with `{user_id, registration_status: "PENDING_PROFILE", next: "profile"}`; a session cookie is set; the account row exists with `PENDING_PROFILE` and no role |
| 2 | a `register` code for a number whose account is `PENDING_PROFILE` (abandoned wizard) | POST | 200 — the incomplete account is resumed, not duplicated; one account row; session cookie set |
| 3 | a `register` code for a number whose account is `COMPLETE` | POST | 409 with code `E01002`; the client is told to use `POST /sessions/` |
| 4 | a code issued for the `login` purpose | POST it to `/users/` | 401 with `E01001` — purpose is part of the check, so codes never mix |
| 5 | a valid outstanding code | POST with a wrong code five times (`OTP_MAX_ATTEMPTS`), then with the right one | each wrong guess is 401 `E01001`; the fifth destroys the code, so the right one is refused too |
| 6 | a code that was just used successfully | POST the same code again | 401 `E01001` — verification consumes, so replay fails |
| 7 | a non-canonical number (bare 10 digits, `+91` with a leading 0) | POST with any OTP | 400 with `E00001` on `mobile_number` — the number is validated before the code is ever looked at; no account created |
| 8 | user1 holds a `register` code for their number; user2 holds one for theirs | user2 POSTs user1's code with **user2's** number, then user2's code with **user1's** number | both are 401 `E01001` — a code is bound to the number it was issued for, and no account is created for either |
| 9 | user1 requested a `register` code, and user2 has seen it | user2 races: POSTs the code with user1's number first; user1 then POSTs the same code | user2 gets 201 and the account; user1's own attempt is 401 `E01001` — the code is consumed by whoever presents it first, which is exactly why the code must stay secret |
| 10 | a valid outstanding code | POST a wrong code four times (below `OTP_MAX_ATTEMPTS`), then the right one | the wrong guesses are 401 `E01001`, but the code survives them: the right one is 201 |
| 11 | four wrong guesses are already counted against the outstanding code | the cooldown passes, a **fresh** code is issued, then four more wrong guesses and the right one | the right code is 201 — issuing a code resets the attempt counter (spec 0005 §5.1), so a re-send is a fresh start, not a step closer to lockout |

Notes:

- The response carries **no `Location` header** — spec 0005 §4.1 shows one,
  but no user-detail route exists to point at; `user_id` in the body is what
  callers use (current behavior, documented in the view).
- Tests: `apps/users/tests/integration/test_user_create_flow.py`.

## Sessions — login, the account-state table, logout

ID: USER-SESSION
Endpoints: `POST /sessions/` · `DELETE /sessions/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a complete litigant with a password | POST `{mobile_number, password}` | 200 with `registration_status: "COMPLETE"`, `approval_status: null`, `next: null`; a session cookie is set |
| 2 | an accepted advocate | POST `{mobile_number, otp}` with a `login` code | 200 with `approval_status: "ACCEPTED"`, `next: null`; replaying the same OTP is 401 `E01003` |
| 3 | an advocate whose registration is `PENDING` | POST valid credentials | 403 with `E01013` and **no session** — a follow-up call to a gated endpoint is unauthenticated (403 `E00102`) |
| 4 | a clerk whose registration is `REJECTED` | POST valid credentials, then call a gated endpoint | 200 with `next: "resubmit"` and a cookie; the gated call is refused 403 `E00104`; the resubmission endpoint is reachable |
| 5 | an incomplete account (`PENDING_PROFILE`) | POST valid credentials | 200 with `next: "profile"` — an incomplete account can log in to resume the wizard |
| 6 | a complete account whose accepted terms are behind `CURRENT_TERMS_VERSION` | POST valid credentials | 200 with `next: "terms"`; session issued but gated |
| 7 | a complete account | POST with both `otp` and `password`, then with neither | both 400 with `E01008` — exactly one credential |
| 8 | accounts and non-accounts | POST a wrong password, an unknown number, and a wrong OTP | all three are the identical 401 with `E01003` |
| 9 | a logged-in client | DELETE `/sessions/`, then call a gated endpoint | 204; the follow-up is unauthenticated (403 `E00102`) |
| 10 | a valid outstanding `login` code | POST a wrong OTP five times, then the right one | the wrong guesses are 401 `E01003`; the fifth destroys the code, so the right one is 401 `E01003` too — the attempts machinery is shared by every verification endpoint |
| 11 | user1 holds a `login` code for their number | user2 POSTs user1's code with **user2's** number | 401 `E01003` — codes are bound to the number they were issued for, at login as at registration |

Notes:

- `CURRENT_TERMS_VERSION` is bumped with `override_settings` for row 6 — the
  setting is read at request time, so no restart is simulated.
- Tests: `apps/users/tests/integration/test_session_flow.py`.

## Completing registration — the wizard's last step

ID: USER-REGISTER
Endpoints: `POST /litigants/` · `POST /power-of-attorneys/` · `POST /advocates/` · `POST /clerks/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a logged-in `PENDING_PROFILE` account | POST the litigant body (`name`, `email`, `password`, `terms_accepted: true`) | 201 with `registration_status: "COMPLETE"`, `role: "LITIGANT"`, `next: null`; a `LitigantProfile` row exists; terms are stamped server-side (`terms_version_accepted` = `CURRENT_TERMS_VERSION`, timestamp ≈ now); account and profile audit `created_by` is the account itself; **the session survives** the password set |
| 2 | a logged-in `PENDING_PROFILE` account | POST the power-of-attorney body | 201 on its own path with a `PowerOfAttorneyProfile` row; session kept; no verification is queued |
| 3 | a logged-in `PENDING_PROFILE` account | POST the advocate body as multipart (`profile.bar_registration_id`, `profile.advocate_type`, `bar_id_document`) | 201; profile is `PENDING` with the claim stored unverified; the document is a stored `File` tagged `bar-council-id` owned by the user; **the session is dead in the same response** (a follow-up is 403 `E00102`) |
| 4 | a logged-in `PENDING_PROFILE` account | POST the clerk body as multipart | 201; `clerk_registration_number` stored, profile `PENDING`; logged out |
| 5 | a logged-in `PENDING_PROFILE` account | POST `/advocates/` with a JSON body; then multipart without `bar_id_document` | 415 (multipart only); 400 with `E00002` on `bar_id_document` |
| 6 | a logged-in `PENDING_PROFILE` account | POST an advocate body whose document the files module refuses (an `.exe` in PDF clothing) | 400 on `bar_id_document`; no `File` row, no profile, account still `PENDING_PROFILE` |
| 7 | a logged-in `PENDING_PROFILE` account, and another advocate already holding `KER/1234/2019` | POST an advocate body with the same `bar_registration_id` | 400 on `profile.bar_registration_id`; account still `PENDING_PROFILE` with no profile; the uploaded document is discarded (no `File` row) — account and profile can never disagree |
| 8 | a complete account | POST any of the four endpoints again | 409 with `E01004` |
| 9 | a logged-in `PENDING_PROFILE` account | POST with `terms_accepted: false`, then with it missing | 400 with `E01010` on `terms_accepted`; 400 with `E00002` on `terms_accepted` |
| 10 | a logged-in `PENDING_PROFILE` account, and another account holding `asha@example.com` | POST with that email | 400 with `E01009` on `email` |
| 11 | a logged-in `PENDING_PROFILE` account | POST with a password failing `AUTH_PASSWORD_VALIDATORS` | 400 with `E01011` on `password`; account unchanged |

Notes:

- `terms_version` / `terms_accepted_at` sent in the body are dropped, never
  honored (spec 0005 §6.3) — row 1's terms assertions pin the server-set side.
- Row 7's `File` assertions use the same `InMemoryStorage` +
  `STORAGES`-override pattern as the files suite.
- Tests: `apps/users/tests/integration/test_registration_flow.py`.

## The current account and the terms screen

ID: USER-ME
Endpoints: `GET /users/me/` · `POST /users/me/terms/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a mid-registration (`PENDING_PROFILE`) session | GET `/users/me/` | 200 with `registration_status: "PENDING_PROFILE"`, `profile: null`, null terms fields, `has_current_terms: false` — gated on `IsAuthenticated` alone |
| 2 | a complete advocate | GET `/users/me/` | 200: account fields plus the profile (`bar_registration_id`, `advocate_type`, `approval_status`, timestamps); the profile's `name` is **not** returned — `name` comes from the account |
| 3 | a complete litigant | GET `/users/me/` | 200: the profile carries only `id`, `created_at`, `updated_at` — no `approval_status`, because there is no claim |
| 4 | a complete account holding an old terms version | POST `terms_accepted: true` | 200 with `current_terms_version` = `terms_version_accepted` = `CURRENT_TERMS_VERSION`, a server-set timestamp, `has_current_terms: true`, `next: null` |
| 5 | the account from row 4 | POST `terms_accepted: true` again | 200, and `terms_accepted_at` is **unchanged** — a repeat writes nothing |
| 6 | a logged-in account | POST `terms_accepted: false`; then with the field missing | 400 `E01010` on `terms_accepted`; 400 `E00002` on `terms_accepted` |
| 7 | no session | GET `/users/me/` | 403 with `E00102` |

Notes:

- Rows 4–5 use `override_settings(CURRENT_TERMS_VERSION=2)` on an account
  that accepted version 1 — the post-publication situation from spec 0005 §6.5.
- Tests: `apps/users/tests/integration/test_me_and_terms_flow.py`.

## Access gates — one session walking the defaults

ID: USER-GATES
Endpoints: the default permission classes (`IsAuthenticatedAndRegistered`, `IsNotAwaitingApproval`, `HasAcceptedCurrentTerms`) against `GET /advocates/?search=` as the representative gated endpoint

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a fresh `PENDING_PROFILE` session | GET the gated endpoint, then complete registration (litigant) and call again | 403 with `E01006` first — while `GET /users/me/` and the wizard endpoint stay reachable; 200 after completing |
| 2 | a complete account behind on terms | GET the gated endpoint, then accept the terms and call again | 403 with `E01007` first; 200 after — registration status and terms currency fail differently because the remedies differ |
| 3 | a rejected advocate's gated session | GET the gated endpoint; then the §7.5 allow-list | 403 with `E00104`; `GET /users/me/`, `POST /users/me/terms/`, the resubmission endpoint and `DELETE /sessions/` are all reachable |
| 4 | no session at all | GET the gated endpoint | 403 with `E00102` — a missing credential, distinct from every gate above |

Notes:

- These rows pin that the gates are **default** permission classes failing
  closed (spec 0005 §9.3): the gated endpoint opts into nothing.
- Tests: `apps/users/tests/integration/test_access_gates_flow.py`.

## Password reset — two calls, one window

ID: USER-PASSWORD-RESET
Endpoints: `POST /auth/password-reset/verify/` · `POST /auth/password-reset/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a complete account and a `password_reset` code for its number | POST verify, then POST `{new_password}` | verify is 200 with `expires_in` = `PASSWORD_RESET_WINDOW_SECONDS`; reset is 204; login with the old password is 401 `E01003`, with the new one 200 |
| 2 | a verified session | call a gated endpoint before resetting | still 403 `E00102` — verification marks the session but logs nobody in |
| 3 | a `password_reset` code | verify with a wrong code; verify a code issued to an unknown number; verify a code for an incomplete account | all three are the identical 401 with `E01001` — the endpoint cannot enumerate registered numbers |
| 4 | a session that never verified | POST `{new_password}` | 401 with `E01014` |
| 5 | a session that already reset once | POST `{new_password}` again | 401 `E01014` — the permission is single-use |
| 6 | a verified session | POST a weak password, then a strong one | 400 with `E01011` on `new_password`, and the permission is **not** spent: the strong retry is 204 |
| 7 | a second client logged into the same account | the first client resets the password | the second client's next call is 403 `E00102` — the new hash invalidates every existing session |
| 8 | a session verified more than `PASSWORD_RESET_WINDOW_SECONDS` ago | POST `{new_password}` | 401 `E01014` |
| 9 | a valid outstanding `password_reset` code | verify with a wrong code five times, then with the right one | the wrong guesses are 401 `E01001`; the fifth destroys the code, so the right one is refused too and the session is never marked — the attempts machinery is shared by every verification endpoint |

Notes:

- Row 8 advances the clock by monkeypatching `time.time` in
  `apps.users.services.password`, not by sleeping; the window setting itself
  is read per request (spec 0005 §4.5).
- Tests: `apps/users/tests/integration/test_password_reset_flow.py`.

## Verification — the 0010 round trip

ID: USER-VERIFICATION
Endpoints: `apps.users.tasks.request_registration_verification` · the 0010 approve/reject hooks (`apps.users.hooks`)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | an advocate just registered (multipart, bar ID stored) | the commit fires and the queued actor runs in-process | exactly one message was queued after commit; the actor raises an `ADVOCATE_REGISTRATION` request: requester is the registrant, `data` is `{name, bar_registration_id}`, one approval routed to the seeded `BAR_ID_APPROVER` group, and the request's document is the **same stored file id** — linked, not re-uploaded |
| 2 | the actor from row 1 already ran | it runs again (a duplicate delivery) | no second request — the actor is idempotent |
| 3 | a queued message whose user (or profile) is gone; a deactivated request type | the actor runs | the first is logged and dropped; the second raises so Dramatiq retries |
| 4 | the raised request | the `BAR_ID_APPROVER` approver approves it (0010 `services.decide`) | the profile moves to `ACCEPTED` with `updated_by` the approver; the advocate's next login is 200 with `next: null` and gated endpoints open |
| 5 | the raised request | the approver rejects it with comments | the profile moves to `REJECTED` with `updated_by` the approver; the reason stays on `RequestApproval.comments` — the profile carries no reason; the advocate's next login is 200 with `next: "resubmit"` |
| 6 | a clerk just registered | the queued actor runs | a `CLERK_REGISTRATION` request is raised with `{name, clerk_registration_number}` |

Notes:

- Messages are inspected and run through the stub broker
  (`dramatiq.get_broker()` under `config.settings.test`), the pattern the
  unit suite uses; `captureOnCommitCallbacks(execute=True)` fires the
  scheduling from the registration POST.
- The `BAR_ID_APPROVER` group, both request types and their approval steps
  come from the session seed (`data/seed/core/auth`,
  `data/seed/core/dristi_requests`) — the product's own reference data, not
  factories; the approver is a user added to that group.
- The numbering configuration (`tenant/state_code`) is provided by an autouse
  fixture, as in the dristi_requests suite.
- Tests: `apps/users/tests/integration/test_verification_flow.py`.

## Correcting a rejected registration

ID: USER-RESUBMIT
Endpoints: `GET /users/me/registration/resubmission/` · `POST /users/me/registration/resubmission/`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a rejected advocate (request rejected with "Bar ID is illegible.") | GET the resubmission endpoint | 200 with `application_id`, `approval_status: "REJECTED"`, `officer_message` and `rejected_at` from the current round, and the claim as last submitted (`name`, `email`, `registration_number`, `document: {file_id, file_name}`) |
| 2 | the same rejected advocate | POST the corrected claim as multipart with a new document | 200 with the **same** `application_id` and `approval_status: "PENDING"`; the request's `version` incremented; profile and account hold the corrected values; the new document replaces the request's links; the session is dead |
| 3 | a pending advocate, an accepted advocate, a litigant, an incomplete account | GET the resubmission endpoint | 404 with `E01015` for all four — no rejected registration to correct |
| 4 | a pending advocate | POST a corrected claim with a document | 409 with `E01012`, checked **before** the body is validated: no `File` row is stored |
| 5 | a rejected advocate, and another profile holding `KER/9999/2020` | POST the corrected claim with that registration number | 400 with `E00010` on `registration_number`; the profile stays `REJECTED`, the request untouched |
| 6 | a rejected advocate | POST with a document the files module refuses | 400 on `bar_id_document`; the profile stays `REJECTED`; the request untouched |
| 7 | a rejected advocate | POST with `mobile_number`, `role`, `password` or `terms_accepted` in the body alongside a valid correction | the correction applies; none of those fields change — the serializer does not declare them |
| 8 | the resubmitted request from row 2 | the approver approves it | the profile moves to `ACCEPTED`; the advocate's next login is 200 with `next: null` — the loop closes on the same `application_id` |

Notes:

- Row 8 is the full circle of spec 0005 §7: register → reject → correct →
  approve, across three sessions and one request id.
- Tests: `apps/users/tests/integration/test_resubmission_flow.py`.

## Finding an advocate

ID: USER-ADVOCATE-SEARCH
Endpoints: `GET /advocates/?search=`

| # | Given | When | Then |
|---|-------|------|------|
| 1 | three accepted advocates, one named by profile name and one differing on the account | a complete litigant GETs `?search=menon` | 200 with the matching advocates only, each carrying exactly `{id, name, bar_registration_id}` — no contact details, since any registered user can search |
| 2 | an accepted advocate | GET with a fragment of their `bar_registration_id` | 200 with that advocate |
| 3 | a pending and a rejected advocate whose names match | GET the matching search | neither appears — only `ACCEPTED` profiles are listed |
| 4 | a complete account | GET with one character; GET with no `search`; GET with a NUL byte in it | 400 `E00007` on `search`; 400 `E00007` on `search`; 400 `E00001` on `search` (the PostgreSQL guard) |
| 5 | `ADVOCATE_SEARCH_THROTTLE_RATE` set to a small rate | GET past the limit as one user | 429; another user is not throttled — the limit is per user |

Notes:

- Test settings disable the throttle (`ADVOCATE_SEARCH_THROTTLE_RATE = ""`);
  row 5 overrides it back on with `override_settings`.
- Tests: `apps/users/tests/integration/test_advocate_search_flow.py`.

## The admin — evidence stays evidence

ID: USER-ADMIN
Endpoints: the user change view (`/admin/users/user/<id>/change/`)

| # | Given | When | Then |
|---|-------|------|------|
| 1 | a complete account with accepted terms | a superuser GETs the admin change view | the terms fields (`terms_accepted_at`, `terms_version_accepted`), `password`, `last_login` and the audit fields render read-only — editable evidence is not evidence (spec 0005 §6.3) |
| 2 | the same account | the superuser POSTs a change (a corrected `name`) through the admin | 302; the name changes; the terms evidence and the password hash are byte-identical |

Notes:

- Real admin POSTs through a Django test `Client` with `force_login`, per
  spec 0037 §5.
- Tests: `apps/users/tests/integration/test_user_admin_flow.py`.
