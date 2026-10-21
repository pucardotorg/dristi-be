# Registration Specification: Account Creation and Profile Completion

## Status
Proposed

## 1. Goal

Create user accounts for four user types — litigant, power of attorney, advocate and advocate clerk — over a multi-step wizard, such that:

- Registration and login are cookie-based throughout. The wizard issues a
  session at `POST /users/` and every later step depends on it, so these
  endpoints accept no other credential. This scopes the flow, not the project:
  spec 0000 section 6.3 keeps token authentication as a supported direction for
  APIs that need it.
- A registration abandoned midway is resumable, never corrupt, and never locks the user out.
- The type-specific profile row and the account can never disagree about whether registration finished.
- Terms acceptance is provable after the fact, including which version was accepted.
- A forgotten password is recoverable without revealing which numbers hold an account.

Registration does not decide an advocate's or clerk's claim. It stores the claim and the bar council ID, then raises a request under 0010 (Generic Request & Approval Workflow), which owns the approver routing and the decision. This app applies the outcome through 0010 hooks (section 7).

## 2. Account Model

The mobile number is the login identifier. Django's "username" is whatever field `USERNAME_FIELD` names, so no field called `username` is needed.

```python
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models


class RegistrationStatus(models.TextChoices):
    PENDING_PROFILE = "PENDING_PROFILE"
    COMPLETE        = "COMPLETE"


class User(AbstractBaseUser, PermissionsMixin):
    mobile_number = models.CharField(max_length=15, unique=True, db_index=True)
    name          = models.CharField(max_length=256, blank=True)
    email         = models.EmailField(null=True, blank=True, unique=True)
    role          = models.CharField(max_length=32, null=True, choices=Role.choices)

    registration_status = models.CharField(
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.PENDING_PROFILE,
    )
    terms_accepted_at      = models.DateTimeField(null=True)
    terms_version_accepted = models.PositiveIntegerField(null=True)

    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD  = "mobile_number"
    REQUIRED_FIELDS = ["name"]
```

### 2.1 Why `AbstractBaseUser` rather than `AbstractUser`?

`AbstractUser` ships a `username` field carrying a `UnicodeUsernameValidator`. Storing a phone number in it means overriding the validator and keeping a field whose name no longer describes its contents. `AbstractBaseUser` provides `password`, `last_login` and the hashing machinery; `PermissionsMixin` provides `is_superuser`, `groups` and `user_permissions`. Nothing is lost.

### 2.2 Why a `registration_status` enum rather than inferring from nulls?

Incompleteness must be a named, queryable state rather than something derived from whichever field happens to be empty. A derived test — `terms_accepted_at IS NULL`, say — conflates "never finished signing up" with "has not accepted the current terms," and the two require different remedies (section 6).

### 2.3 Why not `is_active = False` for incomplete accounts?

`ModelBackend.user_can_authenticate()` rejects inactive users, so an incomplete account could not authenticate and could therefore never resume. `is_active` means "this account is disabled," not "this account is unfinished."


## 3. Profile Models

One profile per account, keyed by a `OneToOneField`. All three carry `name`;
the two professional profiles additionally carry a registration claim and the
state of that claim.

```python
class ApprovalStatus(models.TextChoices):
    PENDING  = "PENDING",  "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"
    REJECTED = "REJECTED", "Rejected"


class AdvocateType(models.TextChoices):
    CIVIL    = "CIVIL",    "Civil"
    CRIMINAL = "CRIMINAL", "Criminal"


class AdvocateProfile(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="advocate_profile",
    )
    name                = models.CharField(max_length=256, blank=True)
    bar_registration_id = models.CharField(max_length=64, unique=True)
    advocate_type       = models.CharField(
        max_length=16, choices=AdvocateType.choices, null=True, blank=True
    )
    approval_status     = models.CharField(
        max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING
    )
```

`ClerkProfile` is identical with `clerk_registration_number` in place of
`bar_registration_id`, and without `advocate_type`. `LitigantProfile` carries
`name` and nothing else — there is no claim to approve, so it has no
`approval_status`. `PowerOfAttorneyProfile` is identical to `LitigantProfile`,
for the same reason.

`bar_registration_id` is the user's own claim and is stored unverified.
Verification happens through a 0010 request, not through fields on the profile.
The profile carries only the outcome; a rejection's reason stays on the request
(section 7.3).

### 3.1 Why `approval_status` lives on the profile rather than being inferred

The same argument as `registration_status` in section 2.2: the state of a claim
must be a named, queryable value rather than something derived from whichever
field happens to be set. Registration always writes `PENDING`; the endpoint
does not accept the field, and only a 0010 request moves it. That keeps the
claim and its verdict in one row without letting the claimant set the verdict.

`LitigantProfile` and `PowerOfAttorneyProfile` have no such field because a
litigant or power of attorney holder makes no claim that anyone approves.

### 3.2 Why `name` is on the profile as well as the account

`User.name` is who the account holder is. The profile `name` is the name the
claim is filed under, which for a professional need not be identical — a bar
roll may carry a different form of the name than the person uses day to day.
Registration seeds both from the same value; nothing yet lets them diverge, and
if they need to, the profile `name` moves into the nested `profile` block.

### 3.3 Why `advocate_type` is optional rather than defaulted

The field records the practice area an advocate works in. `POST /advocates/`
accepts it in the nested `profile` block, but does not require it.

Omitting it leaves the column null. There is no default, because a default
would have every advocate who skipped the question asserting a practice area
they never chose — and nothing downstream could distinguish that from a
deliberate answer. Null means "not stated", which is a different fact from
either `CIVIL` or `CRIMINAL`.

Unlike `approval_status`, this is the advocate's own claim and is theirs to
set, so it is accepted from the request body. Like `bar_registration_id`, it is
stored unverified.

## 4. Endpoints

Every path carries a trailing slash. DRF's `DefaultRouter` generates them that
way and the project's other apps are routed through it, so registration follows
the same convention rather than introducing a second one. The distinction is not
cosmetic: Django will redirect a slash-less `GET` to the canonical form, but it
refuses to do so for a `POST`, because the redirect would discard the request
body. A client that guesses wrong on these endpoints gets a failure, not a
redirect.

### 4.1 Verification and account creation

```http
POST   /auth/otp/request/     { mobile_number, purpose: "register" }     no credential
POST   /users/                { mobile_number, otp }                     OTP is the credential
POST   /sessions/             { mobile_number, otp }                     OTP is the credential
```

None of the three carries a session cookie, but only the first is genuinely
unauthenticated. On `POST /users/` and `POST /sessions/` the **OTP is the
credential** — it authorises the call exactly the way a password does at login,
and possession of the handset is what it proves. Reading these as "no auth"
invites the mistake of treating the body as untrusted-but-harmless input; it is
in fact a single-use secret and must be handled like a password (never logged,
never echoed back, consumed on use — section 5.1).

`POST /users/` creates the account, issues a session cookie, and returns the account's state:

```http
201 Created
Location: /users/8f2a.../

{ "user_id": "8f2a...", "registration_status": "PENDING_PROFILE", "next": "profile" }
```

| Code | Condition |
|---|---|
| `201` | New account created |
| `200` | Incomplete account already existed — resumed, cookie set |
| `409` | Account already `COMPLETE`; the caller should use `POST /sessions/` |

#### 4.1.1 Why is the endpoint named `/users/` and not `/auth/otp/verify/`?

The call creates a row. An endpoint named `verify` reads as a side-effect-free check, and the next reader of the route list will assume it is one. `POST /users/` names the resource created; the OTP is the credential authorising the call, the same role a password plays at login.

#### 4.1.2 Why does `POST /sessions/` return `registration_status`?

An incomplete account can log in. Without the status in the response, the client receives a `200` and a cookie and then fails against every gated endpoint with no explanation. Returning it gives the client a single rule regardless of which endpoint issued the session: if `registration_status != COMPLETE`, route to the wizard.

The same holds for approval and for terms. The response also carries
`approval_status` (null for litigants, power of attorney holders, and an
account with no profile yet)
and `next`:

```json
{ "user_id": "8f2a...", "registration_status": "COMPLETE", "approval_status": "REJECTED", "next": "resubmit" }
```

| Account state | Code | Session | `next` |
|---|---|---|---|
| `PENDING_PROFILE` | `200` | issued | `"profile"` |
| Advocate or clerk, `PENDING` | `403` | not issued | `null` |
| Advocate or clerk, `REJECTED` | `200` | issued, gated (section 7.5) | `"resubmit"` |
| Current terms not held (section 4.4) | `200` | issued, gated | `"terms"` |
| Advocate or clerk `ACCEPTED`, litigant or power of attorney | `200` | issued | `null` |

The rows are checked in that order and the first match wins. The wizard
collects terms itself, so `"profile"` beats `"terms"`; a rejected registration
opens nothing until it is resubmitted, so `"resubmit"` beats `"terms"`.

The `403` is a standard error (spec 0000 section 9) with code `E01013`
(approval pending); the client branches on that code rather than on the
account-state fields, which the error body does not carry.

#### 4.1.3 Rate limit on OTP requests

`POST /auth/otp/request/` sends an SMS on every call and requires no credential
to reach. Once a code has been sent to a mobile number, a second request for
that same number is refused for the length of the resend cooldown, and it comes
from a user tapping "resend".

The cooldown is **configurable, not hardcoded**. It is read from server
configuration as a whole number of seconds:

```bash
OTP_RESEND_COOLDOWN_SECONDS=30
```

The default is 30 seconds. The value must be a positive integer; a value of zero
or less disables the cooldown and is a misconfiguration, so it is rejected at
startup rather than silently permitting unlimited resends.

Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header
giving the seconds remaining. The response must not reveal whether the number
belongs to an existing account.

**How it is enforced.** A cache key whose presence *is* the cooldown. Each
request builds a key from the mobile number alone — not the purpose, or
alternating `register` and `login` would give one number two windows — and
tries to
write it with `cache.add()`, storing the time at which a resend becomes allowed
and an expiry of `settings.OTP_RESEND_COOLDOWN_SECONDS`. `cache.add()` is the
whole mechanism: one atomic operation that writes only when the key is absent
and reports whether it wrote. If the write succeeds, no cooldown was active and
the SMS goes out. If it fails, a code was sent within the cooldown window, so
the request is refused and the stored retry time gives the seconds left for
`Retry-After` (never less than 1). The key expires by itself, so there is
nothing to clean up.

The setting is read at request time, not captured at import time, so a changed
value takes effect on the next request without a code change. Keys written
before the change keep the expiry they were written with; the new value applies
to keys written after it.

#### 4.1.3.1 How the code is delivered

Delivery is not this app's job. The code is handed to the shared messaging app:

```python
enqueue_sms(
    message_key=MESSAGE_KEYS[purpose],      # per purpose, so the wording fits
    recipient={"phone_number": mobile_number},
    context={"otp": code},
)
```

That writes a `MessageLog` row and hands the work to a Dramatiq worker, so a
slow SMS gateway cannot hold the request open, and every send has a durable
record with a status, an attempt count and a provider message id.

Each purpose has its own template, resolved by key at send time:

| Purpose | Template |
|---|---|
| `register` | `ACCOUNT_REGISTRATION_OTP_SMS` — seeded by a users migration |
| `login` | `ACCOUNT_LOGIN_OTP_SMS` — ships with the messaging app |
| `password_reset` | `ACCOUNT_PASSWORD_RESET_OTP_SMS` — seeded by a users migration |

A purpose without a template is a runtime failure rather than a compile-time
one, so a test asserts every member of `Purpose.CHOICES` has a seeded template.

**Known consequence: the code is written to the database.** `MessageLog.context`
holds `{"otp": "..."}` in plaintext, and once rendered so does
`rendered_content`. This is at odds with the reasoning in section 5.1 — the
cache deliberately stores only a keyed digest, with a TTL, because the code is
a credential. A `MessageLog` row has no TTL and appears in every backup. The
exposure is narrow (a five-minute window, and database access is required) but
it is real, and it arrived as a side effect of reusing the shared pipeline
rather than as a decision. Resolving it means either scrubbing `context` and
`rendered_content` on OTP-category logs once they are sent, or applying a short
retention policy to them. Both are changes in the messaging app.

#### 4.1.3.2 Why the cooldown is configuration rather than a constant

The right interval is an operational judgement, not a property of the design. It
trades SMS cost and abuse resistance against how long a user whose first message
never arrived must wait, and the balance differs between environments — tests
need it at zero-cost speed, staging needs it short enough not to obstruct manual
QA, production needs it long enough to blunt enumeration and bill-running. A
literal in the throttle code forces a deploy to retune something that should be
an environment variable, and guarantees the test suite either sleeps or
monkey-patches.

DRF's `SimpleRateThrottle` cannot express this rule. Its rates are per second,
minute, hour or day, so `2/min` would permit two messages back to back and then
nothing for the rest of the minute — not a fixed gap between messages. The
cooldown needs the explicit key.

### 4.2 Completing registration

```http
POST   /litigants/            cookie auth
POST   /power-of-attorneys/   cookie auth
POST   /advocates/            cookie auth
POST   /clerks/               cookie auth
```

The user type is carried by the path, so no `role` field is needed in the body.

Common body:

```json
{
  "name": "...",
  "email": "...",
  "password": "...",
  "terms_accepted": true,
  "terms_version": 3
}
```

Advocate and clerk add a nested object whose contents are written only to the profile table:

```json
"profile": {
  "bar_registration_id": "KER/1234/2019",
  "advocate_type": "CIVIL"
}
```

`advocate_type` is optional and accepts `CIVIL` or `CRIMINAL`; omitting it
leaves the column null (section 3.3). `ClerkProfile` has no equivalent.

The bar council ID document is sent as a `bar_id_document` file field (PDF, JPEG or
PNG). It is required on both `POST /advocates/` and `POST /clerks/`, which
therefore accept `multipart/form-data` only. A multipart body cannot nest, so
the profile block is sent as `profile.<field>` keys.

```http
201 Created

{ "user_id": "8f2a...", "role": "ADVOCATE", "registration_status": "COMPLETE", "next": null }
```

An advocate or clerk is logged out in the same response, since the profile is
now `PENDING` and a pending account holds no session (section 4.1.2). A
litigant or power of attorney holder keeps the session.

#### 4.2.1 Why the password is sent in the request body

This is the conventional Django arrangement, not a shortcut. Django's own
`AuthenticationForm` and `LoginView` take the password as a POST field, and
DRF's built-in token endpoint takes it as a JSON body field. Three rules make it
safe, and all three are requirements here:

- **The body, never the URL.** A password in a query string is written to server
  access logs, kept in browser history, and leaked to third parties through the
  `Referer` header. In the body over HTTPS it is encrypted in transit and not
  logged by default.
- **`write_only=True`** on the serializer field, so the value can be accepted but
  can never be serialised back into a response.
- **`set_password()`**, never assignment to `.password`, since that is what runs
  the configured hasher.

The completion endpoints and `POST /sessions/` must additionally be decorated
with `@sensitive_post_parameters("password", "otp")`. Without it, an unhandled
`500` writes the raw password into Django's error report and into anything
downstream of it, such as Sentry.

#### 4.2.2 Why the document is stored outside the registration transaction

The upload writes to object storage before its row, so a rollback around it
would leave an object with no row to find it by. The upload runs first; if the
registration then fails, the file is discarded. A document the files module
refuses is a `400` on `bar_id_document`.

### 4.3 Reading the current account

```http
GET    /users/me/             cookie auth
```

Returns the account and the profile for its role:

```json
{
  "id": "8f2a...",
  "mobile_number": "+919876543210",
  "name": "...",
  "email": "...",
  "role": "ADVOCATE",
  "registration_status": "COMPLETE",
  "terms_accepted_at": "2026-10-13T09:30:00Z",
  "terms_version_accepted": 3,
  "has_current_terms": true,
  "created_at": "2026-10-01T06:12:00Z",
  "profile": {
    "id": "c41d...",
    "bar_registration_id": "KER/1234/2019",
    "advocate_type": "CIVIL",
    "approval_status": "PENDING",
    "created_at": "2026-10-01T06:15:00Z",
    "updated_at": "2026-10-01T06:15:00Z"
  }
}
```

`profile` holds the role's fields from section 3 plus `id`, `created_at` and
`updated_at` (a litigant's or power of attorney holder's has only those
three). It is `null` before registration completes. The profile's `name` is not
returned; `name` comes from the account.

Gated on `IsAuthenticated` alone: a client mid-registration, or one sent to the
terms screen, needs to read the account to know where it stands.

### 4.4 Accepting the terms

```http
POST   /users/me/terms/       cookie auth     { "terms_accepted": true }
```

For accounts that hold no terms or out-of-date terms (section 6.5).
`HasAcceptedCurrentTerms` is a default permission class, last, after
`IsAuthenticatedAndRegistered` and `IsNotAwaitingApproval`, so this endpoint is gated on `IsAuthenticated`
alone. A missing `terms_accepted` is a `400` with `E00002`; a `false` one is a
`400` with `E01010`, reported on `terms_accepted`. The response:

```json
{
  "current_terms_version": 3,
  "terms_version_accepted": 3,
  "terms_accepted_at": "2026-10-13T09:30:00Z",
  "has_current_terms": true,
  "next": null
}
```

- **A repeat acceptance writes nothing.** Re-stamping would replace the real
  acceptance time with the time of a repeat click.
- **There is no GET.** `GET /users/me/` already returns the terms fields, and
  login's `next` says when the terms screen is due (section 4.1.2).

### 4.5 Password reset

```http
POST   /auth/otp/request/            { mobile_number, purpose: "password_reset" }   no credential
POST   /auth/password-reset/verify/  { mobile_number, otp }                         OTP is the credential
POST   /auth/password-reset/         { new_password }                               verified session
```

Neither step logs anyone in. The code request does not look the number up: a
code is sent to any well-formed number, so the request reveals nothing about
which numbers have accounts.

**Verify** consumes the code, cycles the session key, and stores the account id
and verification time on the session. The client must send the resulting
session cookie with the reset call.

```json
{ "detail": "Code verified. Set a new password.", "expires_in": 600 }
```

A wrong code, an unknown number, an inactive account and an incomplete
registration all return the same `401` with code `E01001` ("Invalid or expired
code.").
An incomplete registration has no password; it resumes through `POST /users/`.

**Reset** sets the password for the verified account:

| Code | Condition |
|---|---|
| `204` | Password set; the user must log in again |
| `400` | `new_password` fails `AUTH_PASSWORD_VALIDATORS` (`E01011`, can be retried) |
| `401` | Session not verified, `PASSWORD_RESET_WINDOW_SECONDS` (default `600`) has passed, or the reset was already used (`E01014`) |

The permission is single-use, and the new password invalidates every existing
session for the account. Section 4.2.1's rules apply to `otp` and
`new_password`.

Design decisions:

- **Two calls, not one.** The code is consumed when entered, and the password
  can then be retried against the validators without spending a new code.
- **Verified state is on the session, not a returned token.** A token would be
  a second bearer secret to issue and revoke. Cycling the session key means the
  privilege attaches to a session id no one could have planted in advance.
- **The window is a setting**, read on each request and rejected at startup if
  below 1, like the resend cooldown (section 4.1.3.2).

## 5. Authentication

Both mobile+password and mobile+OTP are supported by registering two backends. Django tries each in order until one returns a user.

```python
# settings.py
AUTH_USER_MODEL = "users.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",        # mobile + password
    "apps.users.services.backend.OTPBackend",           # mobile + OTP
]
```

`ModelBackend` requires no changes — it authenticates against `USERNAME_FIELD`, which is the mobile number.

```python
class OTPBackend(ModelBackend):
    def authenticate(self, request, mobile_number=None, otp=None,
                     purpose=Purpose.LOGIN, **kwargs):
        if not (mobile_number and otp):
            return None
        if not verify_and_consume_otp(mobile_number, otp, purpose):
            return None
        user = get_user_model().objects.filter(mobile_number=mobile_number).first()
        if user is None or not self.user_can_authenticate(user):
            return None
        return user
```

Three details in that signature carry weight.

**`**kwargs` is mandatory.** Django inspects each backend's signature and
silently skips any that cannot accept the credentials given. `POST /sessions/`
passes `password=None` alongside the OTP, so a backend that could not accept
`password` would be dropped from the loop with no error anywhere.

**`purpose` is part of the check**, because a code issued for registration must
not authorise a login. It is part of the cache key, so the two never mix.

**It subclasses `ModelBackend`, not `BaseBackend`**, so `get_user` — the hook
that reloads the account on every subsequent request from the session cookie —
and `user_can_authenticate` are inherited rather than restated. Only the
credential check differs.

### 5.1 Why the OTP must be consumed, not merely verified

A verified-but-unconsumed code is replayable. Single-use invalidation is the entire security property of the flow; without it the OTP is a static password with a short life.

Wrong guesses are limited too. Each one increments a per-purpose, per-number
cache counter (`cache.add()` then `cache.incr()`, so concurrent guesses count
correctly). At `OTP_MAX_ATTEMPTS` (default `5`) the code is destroyed and a new
one must be requested. Issuing a code resets the counter.

### 5.2 Why the mobile number is validated rather than normalised

`unique=True` compares raw strings, so `+919876543210`, `919876543210` and
`9876543210` would create three separate accounts. Something has to collapse
them to one form.

Two options: rewrite what arrives, or refuse what is not already canonical.
This chooses the second. The client sends E.164 — the frontend prepends the
country code before the number ever leaves it — and the backend enforces that
with a validator on the field:

```python
mobile_number_validator = RegexValidator(regex=r"^\+[1-9]\d{7,14}$")
```

Anything else is a `400`, not a silent correction.

The reasoning is that normalisation on the server is a guess about intent. A
bare ten-digit number could belong to any country, and the rule that prepends
`+91` is a policy the backend has no way to confirm. Refusing is honest about
what the server knows, and it keeps one canonical form in the column without
the server ever inventing digits.

The cost is real and should be understood: `POST /auth/otp/request/` and
`POST /users/` are public, so the frontend's convention is not a guarantee.
A client that posts `9876543210` directly is rejected rather than merged into
the existing account, which is the intended behaviour — but it means the
format contract must be stated in the API documentation, not just assumed.

### 5.3 Why `AUTH_USER_MODEL` must be set before the first migration

Changing it after migrations exist requires rebuilding every migration that references the user model. Set it on day one even if the model initially resembles the default.

## 6. Terms Acceptance

Two fields on the account, not a boolean, and not on the profile.

| Field | Purpose |
|---|---|
| `terms_accepted_at` | When acceptance occurred |
| `terms_version_accepted` | Which version was accepted, as an integer |

### 6.1 Why not a boolean

A bare `true` cannot answer "has this user accepted the current terms?" once terms are versioned, and cannot evidence what was agreed to if acceptance is disputed.

### 6.2 Why the version is an incrementing integer, not a string like `v2.1`

Terms are published in sequence, and the only question ever asked of the stored
value is "is this older than what is in force now?" An integer answers it
directly:

```python
terms_version_accepted < settings.CURRENT_TERMS_VERSION  # stale, re-accept
```

A string supports only equality, which is a weaker question — "did you accept
this exact version?" — and it orders wrongly the moment there are ten of them,
since `"v10" < "v2"` alphabetically. Equality also mishandles an account holding
a *newer* version than the server currently advertises, flagging it stale when
it is not.

`CURRENT_TERMS_VERSION` is therefore an integer in server configuration, and is
incremented by one each time new terms are published.

### 6.3 Why both values are server-set

The timestamp comes from the server clock and the version from server configuration. A client-supplied timestamp or version is unverifiable and therefore worthless as evidence. A missing or `false` `terms_accepted` in the request rejects the registration rather than warning.

### 6.4 Why on the account rather than the profile

Every user type accepts terms; only some have a profile.

### 6.5 Accepting the terms outside the wizard

Accounts that never pass through the wizard (created through filing, or migrated
from an earlier system) reach `COMPLETE` with no terms on record, and every
account is in that position once `CURRENT_TERMS_VERSION` is increased. They
accept through `POST /users/me/terms/` (section 4.4).

## 7. Approval and Rejection

Advocates and clerks are verified; litigants and power of attorney holders
are not.

| Role | Request type | Number verified | Bar ID document |
|---|---|---|---|
| `ADVOCATE` | `ADVOCATE_REGISTRATION` | `bar_registration_id` | required |
| `CLERK` | `CLERK_REGISTRATION` | `clerk_registration_number` | required |

Both request types are seeded by a users migration with one approval step,
routed to the `BAR_ID_APPROVER` group. The request's `data` is the profile
`name` and the number verified.

`approval_status` moves as follows:

| From | To | Moved by |
|---|---|---|
| — | `PENDING` | `POST /advocates/` or `POST /clerks/` |
| `PENDING` | `ACCEPTED` | Approval hook (section 7.2) |
| `PENDING` | `REJECTED` | Rejection hook (section 7.3) |
| `REJECTED` | `PENDING` | `POST /registrations/current/resubmit/` (section 7.4) |

### 7.1 Raising the verification request

A Dramatiq actor, `request_registration_verification`, raises the request. It
is enqueued with `transaction.on_commit`, and the bar ID stored at registration
is linked to the request by `file_id`, not uploaded again.

The actor is idempotent: it locks the user row and does nothing if a
non-cancelled verification request already exists. If the user or profile is
gone, it logs and drops the message; if the request type or approver is
missing, it raises so Dramatiq retries.

#### 7.1.1 Why after commit, and in the background

A message sent before commit lets the worker look for a profile that is not
visible yet. Raising it in the request would let a slow or failing request
engine fail a registration that has already committed.

### 7.2 Approval

When the request is approved, the approval hook sets the profile to `ACCEPTED`,
with `updated_by` set to the approver of the final step. The account then has
full access.

### 7.3 Rejection

When the request is rejected, the rejection hook sets the profile to
`REJECTED`, with `updated_by` set to the rejecting approver. The reason is not
copied onto the profile; it stays in the rejecting `RequestApproval.comments`.

Both hooks run inside the approver's decision transaction, so raising rolls the
decision back. Both are idempotent, because a resubmitted request can be decided
again.

### 7.4 Correcting a rejected registration

```http
GET    /registrations/current/            cookie auth, rejected registrant only
POST   /registrations/current/resubmit/   cookie auth, rejected registrant only
```

A rejected advocate or clerk can log in (section 4.1.2) and reach only these
two endpoints.

`GET /registrations/current/` returns the reason and the claim as last
submitted, to pre-fill the correction screens:

```json
{
  "application_id": "c41d...",
  "approval_status": "REJECTED",
  "role": "ADVOCATE",
  "officer_message": "Bar ID is illegible.",
  "rejected_at": "2026-10-10T09:12:00Z",
  "name": "...",
  "email": "...",
  "mobile_number": "+919876543210",
  "registration_number": "KER/1234/2019",
  "document": { "file_id": "...", "file_name": "bar-id.pdf" }
}
```

`application_id` is the 0010 request's id. `officer_message` and `rejected_at`
come from the rejection in the request's current round, not earlier ones.

`POST /registrations/current/resubmit/` takes the corrected claim as multipart,
since it carries the document:

```
Content-Type: multipart/form-data

name:                ...
email:               ...
registration_number: KER/1234/2019
bar_id_document:     <file>
```

`registration_number` is the bar registration ID for an advocate and the clerk
registration number for a clerk. `bar_id_document` is required for both
roles. The mobile number,
role, password and terms cannot change here.

In one transaction, with the profile row locked:

1. The account and profile take the corrected values.
2. The profile returns to `PENDING`.
3. The same 0010 request is resubmitted with the new `data`: its id is
   unchanged and its `version` increments. A new document replaces the
   request's document links.

The user is logged out, since the account is pending again.

```http
200 OK

{ "application_id": "c41d...", "approval_status": "PENDING" }
```

| Code | Condition |
|---|---|
| `200` | Resubmitted; session ended |
| `400` | Validation failure, or `bar_id_document` refused |
| `403` | Caller is not a rejected advocate or clerk |
| `409` | Nothing to resubmit (`E01012`) |

#### 7.4.1 Why resubmit the same request rather than raise a new one

The application keeps one id across rounds, and approvers see every round's
decision on a single request, keyed by `version`, rather than a chain of
unrelated requests.

### 7.5 Access gates

| `approval_status` | Session | Reachable |
|---|---|---|
| `PENDING` | none | nothing gated |
| `REJECTED` | gated | the section 7.4 endpoints, `GET /users/me/`, `POST /users/me/terms/`, `DELETE /sessions/` |
| `ACCEPTED` | full | everything a registered account can reach |

`IsNotAwaitingApproval`, in the default permission classes after
`IsAuthenticatedAndRegistered` and before `HasAcceptedCurrentTerms`, refuses a
`PENDING` or `REJECTED` advocate or clerk. `IsRejectedRegistrant` admits only a
`REJECTED` one, and guards the section 7.4 endpoints.

### 7.6 Notifications

The messaging app seeds `ACCOUNT_REGISTRATION_APPROVED_SMS` and
`ACCOUNT_REGISTRATION_REJECTED_SMS`, each taking a `link` to the login page.

**Open item: nothing sends them yet.** They belong in the hooks of sections 7.2
and 7.3, enqueued with `transaction.on_commit` so a rolled-back decision does
not notify the registrant.

## 8. Cleanup (NON-PRIORITY)

A scheduled job deletes accounts still in `PENDING_PROFILE` after N days. It is a retention control rather than housekeeping.

### 8.1 Why this should be considered in the future

An abandoned registration keeps personal data for an account that was never completed, and inflates the authentication table with rows that hold a claim on a mobile number.


## 9. Best Practices

1. **Never accept `terms_accepted_at` or `terms_version_accepted` from a request body.** Both come from the server.
2. **Treat an incomplete account as unregistered** when checking whether a mobile number is taken, or an abandoned registration locks that number out permanently.
3. **Apply access gates as default permission classes**, opting out explicitly on the endpoints that need it, so an omission fails closed.
4. **Keep registration status and terms currency as separate checks** — they have different failure remedies.
5. **Require the mobile number in E.164 and reject anything else**, rather than rewriting it server-side. One canonical form in the column, and the server never guesses a country code.
6. **Consume the OTP on use, and destroy it after `OTP_MAX_ATTEMPTS` wrong guesses.** Verification without invalidation permits replay; unlimited guessing permits brute force.
7. **Hold the OTP resend cooldown in the cache, not the database.** `cache.add()` is atomic; a read-then-write check on the last issued row races and sends two messages.
8. **Read the resend cooldown from settings at request time**, never as a literal in the throttle and never captured at import. It is an operational dial, and tests must be able to set it without sleeping.
9. **Treat the OTP in a request body as a credential, not as input.** Never log it, never echo it back, and scrub it from error reports alongside the password.
10. **Set `AUTH_USER_MODEL` before the first migration.**
11. **Reference the user model indirectly** — `settings.AUTH_USER_MODEL` in model definitions, `get_user_model()` in code. Never import `User` directly.
12. **Name endpoints after the resource they act on**, not after the check they perform, so side effects are visible from the route.
13. **Document what `PENDING_PROFILE` means in the API contract**, including that a session issued to such an account is valid but gated.
14. **Answer every failed password-reset verification identically**, so the endpoint cannot be used to find registered numbers.
15. **Never accept `approval_status` from a request body.** Only the 0010 hooks set `ACCEPTED` or `REJECTED`.
16. **Raise the verification request after commit, in the background, idempotently.**
17. **Keep the rejection reason on the request, not the profile.**
18. **Resubmit the same request** rather than raising a new one.
19. **Give a pending advocate or clerk no session, and a rejected one a gated session** — one can only wait, the other must correct and resubmit.
