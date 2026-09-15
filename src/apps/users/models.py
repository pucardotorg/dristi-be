"""Accounts and per-role profiles (spec 0005)."""

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models

from apps.core.models import BaseModel

from .managers import UserManager

# The client sends E.164 (`+919876543210`). The backend does not rewrite what it
# receives; it refuses anything that is not already in that form, so `unique=True`
# is comparing like with like.
mobile_number_validator = RegexValidator(
    regex=r"^\+[1-9]\d{7,14}$",
    message="Enter the mobile number in international format, e.g. +919876543210.",
)


class Role(models.TextChoices):
    """The four user types registration can produce."""

    LITIGANT = "LITIGANT", "Litigant"
    POWER_OF_ATTORNEY = "POWER_OF_ATTORNEY", "Power of attorney"
    ADVOCATE = "ADVOCATE", "Advocate"
    CLERK = "CLERK", "Advocate clerk"


class RegistrationStatus(models.TextChoices):
    """Whether the wizard finished. A named state, never inferred from nulls."""

    PENDING_PROFILE = "PENDING_PROFILE", "Pending profile"
    COMPLETE = "COMPLETE", "Complete"


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    """An account, identified by mobile number."""

    mobile_number = models.CharField(
        max_length=16,
        unique=True,
        db_index=True,
        validators=[mobile_number_validator],
    )
    name = models.CharField(max_length=256, blank=True)
    email = models.EmailField(null=True, blank=True, unique=True)
    role = models.CharField(max_length=32, null=True, blank=True, choices=Role.choices)

    registration_status = models.CharField(
        max_length=20,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.PENDING_PROFILE,
        db_index=True,
    )
    # Two fields, not a boolean: acceptance must be evidenced after the fact,
    # including which version was agreed to (section 6).
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_version_accepted = models.PositiveIntegerField(null=True, blank=True)

    # "Disabled", not "unfinished" — an incomplete account must still be able to
    # authenticate so the registration can be resumed (section 2.3).
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "mobile_number"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)

    def __str__(self):
        """Return the login identifier."""
        return self.mobile_number

    @property
    def is_registration_complete(self) -> bool:
        """Whether the wizard finished."""
        return self.registration_status == RegistrationStatus.COMPLETE

    @property
    def has_current_terms(self) -> bool:
        """Whether the accepted terms are still the ones in force.

        Deliberately separate from `is_registration_complete`: the two have
        different remedies, so they are never collapsed into one check.
        """
        return (self.terms_version_accepted or 0) >= settings.CURRENT_TERMS_VERSION


class LitigantProfile(BaseModel):
    """A litigant's profile. Carries no fields beyond the link to the account."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="litigant_profile",
    )

    def __str__(self):
        """Return a readable label."""
        return f"Litigant profile for {self.user_id}"


class AdvocateProfile(BaseModel):
    """An advocate's profile.

    `bar_registration_id` is the user's own claim and is stored unverified.
    Verification is a 0010 request, not a field here.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="advocate_profile",
    )
    bar_registration_id = models.CharField(max_length=64, unique=True)

    def __str__(self):
        """Return a readable label."""
        return self.bar_registration_id


class ClerkProfile(BaseModel):
    """An advocate clerk's profile. `clerk_registration_number` is unverified."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="clerk_profile",
    )
    clerk_registration_number = models.CharField(max_length=64, unique=True)

    def __str__(self):
        """Return a readable label."""
        return self.clerk_registration_number
