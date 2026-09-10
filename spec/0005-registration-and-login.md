# Registration Specification: Account Creation and Profile Completion

## Status
Proposed

## 1. Goal

Create user accounts for four user types — litigant, power of attorney, advocate and advocate clerk — over a multi-step wizard, such that:

- Authentication is cookie-based throughout, with no second auth mechanism.
- Document upload during registration is authenticated, not anonymous.
- A registration abandoned midway is resumable, never corrupt, and never locks the user out.
- The type-specific profile row and the account can never disagree about whether registration finished.
- Terms acceptance is provable after the fact, including which version was accepted.
- Advocate and clerk claims are recorded as unverified until a scrutiny officer approves them.

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
    terms_version_accepted = models.CharField(max_length=32, null=True)

    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD  = "mobile_number"
    REQUIRED_FIELDS = ["name"]
```

### 2.1 Why `AbstractBaseUser` rather than `AbstractUser`?

`AbstractUser` ships a `username` field carrying a `UnicodeUsernameValidator`. Storing a phone number in it means overriding the validator and keeping a field whose name no longer describes its contents. `AbstractBaseUser` provides `password`, `last_login` and the hashing machinery; `PermissionsMixin` provides `is_superuser`, `groups` and `user_permissions`. Nothing is lost.

### 2.2 Why a `registration_status` enum rather than inferring from nulls?

Incompleteness must be a named, queryable state rather than something derived from whichever field happens to be empty. A derived test — `terms_accepted_at IS NULL`, say — conflates "never finished signing up" with "has not accepted the current terms," and the two require different remedies (section 7).

### 2.3 Why not `is_active = False` for incomplete accounts?

`ModelBackend.user_can_authenticate()` rejects inactive users, so an incomplete account could not authenticate and could therefore never resume. `is_active` means "this account is disabled," not "this account is unfinished."


## 3. Profile Models

One profile per account, keyed by a `OneToOneField`.

```python
class AdvocateProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="advocate_profile",
    )
    bar_registration_id = models.CharField(max_length=64, unique=True)
    document            = models.ForeignKey("documents.Document", on_delete=models.PROTECT)
    approval_status     = models.CharField(
        max_length=16,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    rejection_reason = models.TextField(blank=True)
```

`ClerkProfile` is identical with `clerk_registration_number` in place of `bar_registration_id`. `LitigantProfile` carries no verification fields.

### 3.1 Why `approval_status` defaults to `PENDING` and is never read from the request

An unauthenticated-by-session caller supplies the bar registration number, so it is a claim rather than a verified fact. Storing it is safe precisely because it is stored as unverified. The value must be server-set; a client must never be able to declare itself approved.

### 3.2 Why `on_delete=models.PROTECT` on the document?

The uploaded council ID is the evidence a scrutiny officer reviews. Deleting it out from under a pending profile would leave the officer with nothing to check.

## 4. Endpoints

### 4.1 Verification and account creation

```http
POST   /auth/otp/request      { mobile_number, purpose: "register" }     no auth
POST   /users                 { mobile_number, otp }                     no auth
POST   /sessions              { mobile_number, otp }                     no auth
```

`POST /users` creates the account, issues a session cookie, and returns the account's state:

```http
201 Created
Location: /users/8f2a...

{ "user_id": "8f2a...", "registration_status": "PENDING_PROFILE", "next": "profile" }
```

| Code | Condition |
|---|---|
| `201` | New account created |
| `200` | Incomplete account already existed — resumed, cookie set |
| `409` | Account already `COMPLETE`; the caller should use `POST /sessions` |

#### 4.1.1 Why is the endpoint named `/users` and not `/auth/otp/verify`?

The call creates a row. An endpoint named `verify` reads as a side-effect-free check, and the next reader of the route list will assume it is one. `POST /users` names the resource created; the OTP is the credential authorising the call, the same role a password plays at login.

#### 4.1.2 Why does `POST /sessions` return `registration_status`?

An incomplete account can log in. Without the status in the response, the client receives a `200` and a cookie and then fails against every gated endpoint with no explanation. Returning it gives the client a single rule regardless of which endpoint issued the session: if `registration_status != COMPLETE`, route to the wizard.

### 4.2 Documents

```http
POST   /documents             cookie auth   → returns document_id
DELETE /documents/{id}        cookie auth
```

Advocates and clerks upload the bar council ID before the terms screen. Litigants and PoA holders skip this step.

#### 4.2.1 Why the account is created before the upload

The upload must be authenticated — anonymous file upload permits storage exhaustion and malware hosting on the service's own domain. Creating the account at OTP time means the upload is an ordinary cookie-authenticated request with a real foreign key to its owner, rather than requiring a pre-auth token, a placeholder `uploaded_by_mobile` column, and an ownership check at registration time to prevent one user referencing another's document.

### 4.3 Completing registration

```http
POST   /litigants             cookie auth
POST   /advocates             cookie auth
POST   /clerks                cookie auth
```

The user type is carried by the path, so no `role` field is needed in the body.

Common body:

```json
{
  "name": "...",
  "email": "...",
  "password": "...",
  "terms_accepted": true,
  "terms_version": "v2.1"
}
```

Advocate and clerk add a nested object whose contents are written only to the profile table:

```json
"profile": {
  "bar_registration_id": "KER/1234/2019",
  "document_id": "..."
}
```

## 5. Authentication

Both mobile+password and mobile+OTP are supported by registering two backends. Django tries each in order until one returns a user.

```python
# settings.py
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",   # mobile + password
    "accounts.backends.OTPBackend",                # mobile + OTP
]
```

`ModelBackend` requires no changes — it authenticates against `USERNAME_FIELD`, which is the mobile number.

```python
class OTPBackend(BaseBackend):
    def authenticate(self, request, mobile_number=None, otp=None, **kwargs):
        if not (mobile_number and otp):
            return None
        if not verify_and_consume_otp(mobile_number, otp):
            return None
        return User.objects.filter(
            mobile_number=normalize_mobile(mobile_number)
        ).first()

    def get_user(self, user_id):
        return User.objects.filter(pk=user_id).first()
```

### 5.1 Why the OTP must be consumed, not merely verified

A verified-but-unconsumed code is replayable. Single-use invalidation is the entire security property of the flow; without it the OTP is a static password with a short life.

### 5.2 Why the mobile number must be normalised before storage and lookup

`unique=True` compares raw strings, so `+919876543210`, `919876543210` and `9876543210` create three separate accounts. Django provides `normalize_email` but no phone equivalent — normalisation must be enforced in the manager and in every lookup.

### 5.3 Why `AUTH_USER_MODEL` must be set before the first migration

Changing it after migrations exist requires rebuilding every migration that references the user model. Set it on day one even if the model initially resembles the default.

## 6. Terms Acceptance

Two fields on the account, not a boolean, and not on the profile.

| Field | Purpose |
|---|---|
| `terms_accepted_at` | When acceptance occurred |
| `terms_version_accepted` | Which version was accepted |

### 6.1 Why not a boolean

A bare `true` cannot answer "has this user accepted the current terms?" once terms are versioned, and cannot evidence what was agreed to if acceptance is disputed.

### 6.2 Why both values are server-set

The timestamp comes from the server clock and the version from server configuration. A client-supplied timestamp or version is unverifiable and therefore worthless as evidence. A missing or `false` `terms_accepted` in the request rejects the registration rather than warning.

### 6.3 Why on the account rather than the profile

Every user type accepts terms; only some have a profile.

## 7. Scrutiny Dispatch

For advocate and clerk only:

```http
POST   /scrutiny/registrations
```

Called internally by the completion endpoint, after the transaction commits. The client makes one call and is done.

### 7.1 Why after commit rather than inside the transaction

An outage in the scrutiny service would otherwise roll back a valid registration, and the user would be told their account could not be created when the only failure was a notification. Dispatch via an outbox row or task queue so it can be retried independently.

## 8. Cleanup (NON-PRIORITY)

Two scheduled jobs, both retention controls rather than housekeeping.

| Target | Rule |
|---|---|
| Accounts in `PENDING_PROFILE` | Delete after N days, together with their uploaded documents |
| Documents with no completed account | Delete after N hours |

### 8.1 Why this is not optional

An abandoned registration leaves a scan of a person's identity document in storage for an account that was never completed, and inflates the authentication table with rows that hold a claim on a mobile number.


## 9. Best Practices

1. **Never accept `approval_status` from a request body.** It is server-set to `PENDING` and changed only by the scrutiny workflow.
2. **Never accept `terms_accepted_at` or `terms_version_accepted` from a request body.** Both come from the server.
3. **Treat an incomplete account as unregistered** when checking whether a mobile number is taken, or an abandoned registration locks that number out permanently.
4. **Apply access gates as default permission classes**, opting out explicitly on the endpoints that need it, so an omission fails closed.
5. **Keep registration status and terms currency as separate checks** — they have different failure remedies.
6. **Normalise the mobile number in the manager and in every lookup**, not only at the point of creation.
7. **Consume the OTP on use.** Verification without invalidation permits replay.
8. **Set `AUTH_USER_MODEL` before the first migration.**
9. **Reference the user model indirectly** — `settings.AUTH_USER_MODEL` in model definitions, `get_user_model()` in code. Never import `User` directly.
10. **Name endpoints after the resource they act on**, not after the check they perform, so side effects are visible from the route.
11. **Document what `PENDING_PROFILE` means in the API contract**, including that a session issued to such an account is valid but gated.
