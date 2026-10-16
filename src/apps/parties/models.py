"""Parties to a case: people and institutions (spec 0020 §2-3)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.api.meta import IST_TIMEZONE
from apps.core.models import BaseAuditableModel, BaseModel

# Any phone number, in E.164 form: "+", a country code and the number, digits
# only (e.g. "+919876543210", "+14155552671"). Not limited to Indian mobiles,
# since a party may live abroad or have only a landline. The same pattern is a
# database check, so the database refuses what the model does.
PHONE_NUMBER_REGEX = r"^\+[1-9][0-9]{6,14}$"
phone_number_validator = RegexValidator(
    PHONE_NUMBER_REGEX,
    "Enter the number with its country code, e.g. +919876543210.",
)

# Any phone line, landlines and toll-free numbers included: groups of digits,
# a group optionally in parentheses, e.g. "(080) 2233 4455", separated by a
# space or hyphen, with an optional leading "+". No letters. Written without
# shorthand classes so Postgres and Python read it alike.
CONTACT_NUMBER_REGEX = r"^\+?(\([0-9]+\)|[0-9]+)([ -]?(\([0-9]+\)|[0-9]+))*$"
contact_number_validator = RegexValidator(
    CONTACT_NUMBER_REGEX,
    "Enter digits only, optionally grouped with parentheses, spaces or hyphens"
    " and starting with +.",
)


def today_in_india():
    """Return today's date in India.

    ``TIME_ZONE`` is UTC, so ``timezone.localdate()`` alone would still give
    yesterday for the first five and a half hours of every Indian day.
    """
    return timezone.localdate(timezone=IST_TIMEZONE)


def validate_not_in_future(value):
    """Reject a date after today, in India."""
    if value > today_in_india():
        raise ValidationError("This date cannot be in the future.")


MAX_AGE = 150


def age_on(date_of_birth, day):
    """Return the age in whole years, on ``day``, of someone born on ``date_of_birth``."""
    had_birthday = (day.month, day.day) >= (date_of_birth.month, date_of_birth.day)
    return day.year - date_of_birth.year - (0 if had_birthday else 1)


def _blank_to_none(value):
    """Return ``None`` for a missing or whitespace-only value, else the stripped value."""
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _strip(value):
    """Return a required text value without surrounding whitespace.

    A whitespace-only value becomes the empty string, which "required" rejects.
    """
    return value.strip() if isinstance(value, str) else value


class Gender(models.TextChoices):
    """Supported genders."""

    MALE = "MALE", "Male"
    FEMALE = "FEMALE", "Female"
    OTHER = "OTHER", "Other"
    PREFER_NOT_TO_SAY = "PREFER_NOT_TO_SAY", "Prefer not to say"


class Relation(models.TextChoices):
    """How a person is related to the relative named in ``relative_name``."""

    SON_OF = "SON_OF", "S/O"
    DAUGHTER_OF = "DAUGHTER_OF", "D/O"
    WIFE_OF = "WIFE_OF", "W/O"
    HUSBAND_OF = "HUSBAND_OF", "H/O"
    WARD_OF = "WARD_OF", "Ward of"


class DisabilityStatus(models.TextChoices):
    """Supported disability statuses. ``NONE`` is the default when none is given."""

    NONE = "NONE", "None"
    VISUAL = "VISUAL", "Visual"
    HEARING = "HEARING", "Hearing"
    MOBILITY = "MOBILITY", "Mobility"
    COGNITIVE = "COGNITIVE", "Cognitive"
    OTHER = "OTHER", "Other"


class VerificationLevel(models.TextChoices):
    """How we know a person is who they claim to be (spec 0020 §2.3)."""

    ASSERTED = "ASSERTED", "Asserted"
    CONTACTED = "CONTACTED", "Contacted"
    VERIFIED = "VERIFIED", "Verified"


class EntityType(models.TextChoices):
    """Kinds of legal entity that can be a party (spec 0020 §3.3)."""

    PRIVATE_LIMITED_COMPANY = "PRIVATE_LIMITED_COMPANY", "Private limited company"
    PUBLIC_LIMITED_COMPANY = "PUBLIC_LIMITED_COMPANY", "Public limited company"
    LLP = "LLP", "Limited liability partnership"
    PARTNERSHIP_FIRM = "PARTNERSHIP_FIRM", "Partnership firm"
    PROPRIETORSHIP = "PROPRIETORSHIP", "Proprietorship"
    SOCIETY_TRUST = "SOCIETY_TRUST", "Society / trust"
    OTHER_ENTITY = "OTHER_ENTITY", "Other entity"


class Institution(BaseModel, BaseAuditableModel):
    """A non-human party: a company, firm, society, trust and so on.

    Kept apart from ``organizations.Organization``, which models the court
    hierarchy, so a court can never be recorded as a party by mistake.
    """

    entity_type = models.CharField(max_length=32, choices=EntityType.choices)
    entity_name = models.CharField(max_length=256, db_index=True)
    # Often a landline or toll-free line, so not validated as a mobile number.
    # 20 leaves room for grouping, e.g. "+91 (80) 2233-4455".
    contact_number = models.CharField(
        max_length=20, null=True, blank=True, validators=[contact_number_validator]
    )
    email_address = models.EmailField(max_length=256, null=True, blank=True)
    # Registered office: where notices to the institution are served.
    address = models.ForeignKey(
        "address.Address",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.CheckConstraint(
                check=Q(entity_type__in=EntityType.values),
                name="parties_institution_entity_type_valid",
            ),
            models.CheckConstraint(
                check=Q(contact_number__isnull=True)
                | Q(contact_number__regex=CONTACT_NUMBER_REGEX),
                name="parties_institution_contact_number_valid",
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return self.entity_name

    def clean_fields(self, exclude=None):
        """Validate values as they will be stored.

        The name is trimmed, so a whitespace-only name is rejected as missing,
        and a blank contact number is stored as no number.
        """
        self.entity_name = _strip(self.entity_name)
        self.contact_number = _blank_to_none(self.contact_number)
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        """Validate before every save, so no write path can skip the rules."""
        self.full_clean()
        super().save(*args, **kwargs)


class Person(BaseModel, BaseAuditableModel):
    """One human being the system knows of, registered or not.

    Holds current data. What a filing must preserve is frozen separately in the
    case participant snapshot, and addresses are immutable rows, so editing a
    person never rewrites a court record.
    """

    name = models.CharField(max_length=256)
    phone_number = models.CharField(
        max_length=16,
        null=True,
        blank=True,
        validators=[phone_number_validator],
    )
    email_address = models.EmailField(max_length=256, null=True, blank=True)
    relation = models.CharField(max_length=16, choices=Relation.choices, null=True, blank=True)
    relative_name = models.CharField(max_length=256, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True, validators=[validate_not_in_future])
    # Only for when the date of birth is unknown and an approximate age is
    # stated ("aged about 45"), as is often the case for an accused. It is
    # cleared whenever a date of birth is given: the date of birth is the source
    # of truth, and a stored age alongside it would go stale. ``current_age``
    # gives the age either way.
    age = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(MAX_AGE)]
    )
    gender = models.CharField(max_length=32, choices=Gender.choices, null=True, blank=True)
    institution = models.ForeignKey(
        Institution,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="people",
    )
    designation = models.CharField(max_length=128, null=True, blank=True)
    permanent_address = models.ForeignKey(
        "address.Address",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    correspondence_address = models.ForeignKey(
        "address.Address",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    disability_status = models.CharField(
        max_length=16,
        choices=DisabilityStatus.choices,
        default=DisabilityStatus.NONE,
        # Also the column default, so a row inserted outside Django gets NONE too.
        db_default=DisabilityStatus.NONE,
    )
    verification_level = models.CharField(
        max_length=16,
        choices=VerificationLevel.choices,
        default=VerificationLevel.ASSERTED,
    )
    # NULL until the person registers; unique so one person claims one account.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="person",
    )

    class Meta(BaseModel.Meta):
        """Meta options."""

        verbose_name_plural = "people"
        constraints = [
            models.CheckConstraint(
                check=Q(phone_number__isnull=True) | Q(phone_number__regex=PHONE_NUMBER_REGEX),
                name="parties_person_phone_number_valid",
            ),
            models.CheckConstraint(
                check=Q(verification_level__in=VerificationLevel.values),
                name="parties_person_verification_level_valid",
            ),
            models.CheckConstraint(
                check=Q(age__isnull=True) | Q(age__lte=MAX_AGE),
                name="parties_person_age_valid",
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return self.name

    def clean_fields(self, exclude=None):
        """Validate values as they will be stored.

        The name is trimmed, so a whitespace-only name is rejected as missing;
        a blank phone number or relative's name is stored as none.
        """
        self.name = _strip(self.name)
        # Not given (None or blank) means no disability.
        if not _blank_to_none(self.disability_status):
            self.disability_status = DisabilityStatus.NONE
        self.phone_number = _blank_to_none(self.phone_number)
        self.relative_name = _blank_to_none(self.relative_name)
        # A known date of birth replaces an approximate age.
        if self.date_of_birth not in (None, ""):
            self.age = None
        super().clean_fields(exclude=exclude)

    @property
    def current_age(self):
        """Return today's age: from the date of birth when known, else the stated age."""
        if self.date_of_birth:
            return age_on(self.date_of_birth, today_in_india())
        return self.age

    def save(self, *args, **kwargs):
        """Validate before every save, so no write path can skip the rules.

        ``clean()`` and the field validators (relation needs a relative's name,
        no future date of birth, …) run only in ``full_clean``; without this a
        plain ``Person.objects.create(...)`` would store a record that breaks them.
        """
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        """Check the fields that only make sense together.

        A designation describes a role at an institution, so needs one; a
        relation ("S/O", "W/O" …) names a relative, so needs their name.
        """
        super().clean()
        errors = {}
        if self.designation and not self.institution_id:
            errors["designation"] = "A designation is only allowed when an institution is set."
        if self.relation and not self.relative_name:
            errors["relative_name"] = "Enter the relative's name for this relation."
        if errors:
            raise ValidationError(errors)
