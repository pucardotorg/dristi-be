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

Verifying an advocate's or clerk's claim — uploading the bar council ID and having it approved — is not part of registration. It is raised as a request type under 0010 (Generic Request & Approval Workflow), which owns the document upload, the approver routing and the outcome.

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
`approval_status`.

`bar_registration_id` is the user's own claim and is stored unverified.
Verification happens through a 0010 request, not through fields on the profile.

### 3.1 Why `approval_status` lives on the profile rather than being inferred

The same argument as `registration_status` in section 2.2: the state of a claim
must be a named, queryable value rather than something derived from whichever
field happens to be set. Registration always writes `PENDING`; the endpoint
does not accept the field, and only a 0010 request moves it. That keeps the
claim and its verdict in one row without letting the claimant set the verdict.

`LitigantProfile` has no such field because a litigant makes no claim that
anyone approves.

### 3.2 Why `name` is on the profile as well as the account

`User.name` is who the account holder is. The profile `name` is the name the
claim is filed under, which for a professional need not be identical — a bar
roll may carry a different form of the name than the person uses day to day.
Registration seeds both from the same value; nothing yet lets them diverge, and
if they need to, the profile `name` moves into the nested `profile` block.

### 3.3 `advocate_type` is a column without a writer

The field records the practice area an advocate works in. Nothing sets it
today: it is not accepted in the registration body and no approval flow writes
it. It is deliberately nullable rather than defaulted, so that no row asserts a
practice area nobody supplied. The logic that populates it is out of scope
here.

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

#### 4.1.3 Rate limit on OTP requests

`POST /auth/otp/request/` sends an SMS on every call and requires no credential
to reach. Once a code has been sent to a mobile number, a second request for
that same number is refused for the length of the resend cooldown, and it comes
from a user tapping "resend".

The cooldown is **configurable, not hardcoded**. It is read from server
configuration as a whole number of seconds:


The default is 30 seconds. The value must be a positive integer; a value of zero
or less disables the cooldown and is a misconfiguration, so it is rejected at
startup rather than silently permitting unlimited resends.

Exceeding the limit returns `429 Too Many Requests` with a `Retry-After` header
giving the seconds remaining. The response must not reveal whether the number
belongs to an existing account.

**How it is enforced.** A cache key whose presence *is* the cooldown. Each
request builds a key from the OTP purpose and the mobile number, and tries to
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
  "bar_registration_id": "KER/1234/2019"
}
```

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

## 7. Cleanup (NON-PRIORITY)

A scheduled job deletes accounts still in `PENDING_PROFILE` after N days. It is a retention control rather than housekeeping.

### 7.1 Why this should be considered in the future

An abandoned registration keeps personal data for an account that was never completed, and inflates the authentication table with rows that hold a claim on a mobile number.


## 8. Best Practices

1. **Never accept `terms_accepted_at` or `terms_version_accepted` from a request body.** Both come from the server.
2. **Treat an incomplete account as unregistered** when checking whether a mobile number is taken, or an abandoned registration locks that number out permanently.
3. **Apply access gates as default permission classes**, opting out explicitly on the endpoints that need it, so an omission fails closed.
4. **Keep registration status and terms currency as separate checks** — they have different failure remedies.
5. **Require the mobile number in E.164 and reject anything else**, rather than rewriting it server-side. One canonical form in the column, and the server never guesses a country code.
6. **Consume the OTP on use.** Verification without invalidation permits replay.
7. **Hold the OTP resend cooldown in the cache, not the database.** `cache.add()` is atomic; a read-then-write check on the last issued row races and sends two messages.
8. **Read the resend cooldown from settings at request time**, never as a literal in the throttle and never captured at import. It is an operational dial, and tests must be able to set it without sleeping.
9. **Treat the OTP in a request body as a credential, not as input.** Never log it, never echo it back, and scrub it from error reports alongside the password.
10. **Set `AUTH_USER_MODEL` before the first migration.**
11. **Reference the user model indirectly** — `settings.AUTH_USER_MODEL` in model definitions, `get_user_model()` in code. Never import `User` directly.
12. **Name endpoints after the resource they act on**, not after the check they perform, so side effects are visible from the route.
13. **Document what `PENDING_PROFILE` means in the API contract**, including that a session issued to such an account is valid but gated.