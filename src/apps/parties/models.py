"""Parties to a case: people and institutions (spec 0020 §2-3)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel
from apps.users.models import mobile_number_validator

# Mirrors ``mobile_number_validator`` so the database refuses what the model does.
MOBILE_NUMBER_REGEX = r"^\+91[6-9]\d{9}$"


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
    """Supported disability statuses. NULL on the column means not stated."""

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


class Institution(BaseModel):
    """A non-human party: a company, firm, society, trust and so on.

    Kept apart from ``organizations.Organization``, which models the court
    hierarchy, so a court can never be recorded as a party by mistake.
    """

    entity_type = models.CharField(max_length=32, choices=EntityType.choices)
    entity_name = models.CharField(max_length=256, db_index=True)
    # Often a landline or toll-free line, so not validated as a mobile number.
    contact_number = models.CharField(max_length=16, null=True, blank=True)
    email_address = models.EmailField(max_length=256, null=True, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.CheckConstraint(
                check=Q(entity_type__in=EntityType.values),
                name="parties_institution_entity_type_valid",
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return self.entity_name


class Person(BaseModel):
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
        validators=[mobile_number_validator],
    )
    email_address = models.EmailField(max_length=256, null=True, blank=True)
    relation = models.CharField(max_length=16, choices=Relation.choices, null=True, blank=True)
    relative_name = models.CharField(max_length=256, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
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
        null=True,
        blank=True,
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
                check=Q(phone_number__isnull=True) | Q(phone_number__regex=MOBILE_NUMBER_REGEX),
                name="parties_person_phone_number_valid",
            ),
            models.CheckConstraint(
                check=Q(verification_level__in=VerificationLevel.values),
                name="parties_person_verification_level_valid",
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return self.name

    def clean(self):
        """A designation describes a role at an institution, so needs one."""
        super().clean()
        if self.designation and not self.institution_id:
            raise ValidationError(
                {"designation": "A designation is only allowed when an institution is set."}
            )
