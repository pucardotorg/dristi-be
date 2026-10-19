"""Request validation for the registration and login endpoints."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.api import errors as api_errors

from . import errors
from .documents import validate_registration_document
from .models import (
    AdvocateProfile,
    AdvocateType,
    ApprovalStatus,
    ClerkProfile,
    Role,
    mobile_number_validator,
)
from .services.otp import Purpose
from .verification import VERIFICATIONS

MAX_PASSWORD_LENGTH = 128


class OTPRequestSerializer(serializers.Serializer):
    """Body of POST /auth/otp/request."""

    mobile_number = serializers.CharField(max_length=16, validators=[mobile_number_validator])
    purpose = serializers.ChoiceField(choices=Purpose.CHOICES, default=Purpose.REGISTER)


class MobileOTPSerializer(serializers.Serializer):
    """Body of POST /users. The OTP is the credential authorising the call."""

    mobile_number = serializers.CharField(max_length=16, validators=[mobile_number_validator])
    otp = serializers.CharField(max_length=10, write_only=True)


class SessionCreateSerializer(serializers.Serializer):
    """Body of POST /sessions — mobile plus exactly one credential."""

    mobile_number = serializers.CharField(max_length=16, validators=[mobile_number_validator])
    otp = serializers.CharField(max_length=10, write_only=True, required=False)
    password = serializers.CharField(
        max_length=MAX_PASSWORD_LENGTH,
        write_only=True,
        required=False,
    )

    def validate(self, attrs):
        """Require one credential, not zero and not both."""
        if bool(attrs.get("otp")) == bool(attrs.get("password")):
            raise errors.CREDENTIAL_CHOICE.validation_error()
        return attrs


def _unclaimed_email(value, current):
    """Return the email, or None for none, refusing one another account holds."""
    if not value:
        return None
    taken = get_user_model().objects.filter(email__iexact=value).exclude(pk=current.pk).exists()
    if taken:
        raise errors.EMAIL_TAKEN.validation_error()
    return value


class RegistrationDocumentField(serializers.FileField):
    """The bar ID document: a PDF or image within the size limit."""

    def __init__(self, **kwargs):
        super().__init__(write_only=True, validators=[validate_registration_document], **kwargs)


class RegistrationCompletionSerializer(serializers.Serializer):
    """Common body of POST /litigants, /advocates and /clerks.

    `terms_version` is deliberately not declared. A client-supplied version or
    timestamp is unverifiable and therefore worthless as evidence, so both are
    set from the server; anything sent under that name is dropped.
    """

    name = serializers.CharField(max_length=256)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    password = serializers.CharField(max_length=MAX_PASSWORD_LENGTH, write_only=True)
    terms_accepted = serializers.BooleanField()

    def validate(self, attrs):
        """Run the password through AUTH_PASSWORD_VALIDATORS.

        Object-level rather than per-field so the password can be compared
        against the name and email arriving in this request. The stored row
        holds only a mobile number until `complete_registration` runs, so
        checking against it would let someone pick their own name as their
        password. The candidate is a throwaway carrying the submitted values
        and is never saved.
        """
        candidate = get_user_model()(
            mobile_number=self.context["request"].user.mobile_number,
            name=attrs.get("name", ""),
            email=attrs.get("email") or "",
        )
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise errors.PASSWORD_REJECTED.validation_error({"password": exc.messages}) from exc
        return attrs

    def validate_email(self, value):
        """Reject an email already claimed by another account."""
        return _unclaimed_email(value, self.context["request"].user)

    def validate_terms_accepted(self, value):
        """A missing or false acceptance rejects the registration."""
        if not value:
            raise errors.TERMS_NOT_ACCEPTED.validation_error()
        return value


class AdvocateProfileSerializer(serializers.ModelSerializer):
    """
    Nested profile body for an advocate. Stored as an unverified claim.
    """

    # Optional: an advocate who does not state a practice area leaves the
    # column null rather than being assigned a default they never chose.
    advocate_type = serializers.ChoiceField(
        choices=AdvocateType.choices,
        required=False,
        allow_null=True,
    )

    class Meta:
        """Meta options."""

        model = AdvocateProfile
        fields = ["bar_registration_id", "advocate_type"]


class ClerkProfileSerializer(serializers.ModelSerializer):
    """
    Nested profile body for an advocate clerk. Stored as an unverified claim.
    """

    class Meta:
        """Meta options."""

        model = ClerkProfile
        fields = ["clerk_registration_number"]


class AdvocateRegistrationSerializer(RegistrationCompletionSerializer):
    """Body of POST /advocates, sent as multipart so it can carry the bar ID."""

    profile = AdvocateProfileSerializer()
    bar_id_document = RegistrationDocumentField()


class ClerkRegistrationSerializer(RegistrationCompletionSerializer):
    """Body of POST /clerks.

    The bar ID is optional: only some clerks are asked for one.
    """

    profile = ClerkProfileSerializer()
    bar_id_document = RegistrationDocumentField(required=False)


class RegistrationResubmissionSerializer(serializers.Serializer):
    """Body of POST /registrations/current/resubmit/: the corrected claim.

    The registration steps minus what cannot change: the mobile number was
    proven by OTP and is what the person signs in with, and the role, password
    and terms stand. ``registration_number`` is the bar registration ID for an
    advocate and the clerk registration number for a clerk.
    """

    name = serializers.CharField(max_length=256)
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    registration_number = serializers.CharField(max_length=64)
    bar_id_document = RegistrationDocumentField(required=False)

    def validate_email(self, value):
        """Reject an email already claimed by another account."""
        return _unclaimed_email(value, self.context["request"].user)

    def validate_registration_number(self, value):
        """Reject a number another profile of the same role already claims."""
        user = self.context["request"].user
        verification = VERIFICATIONS[user.role]
        taken = (
            verification.profile_model.objects.filter(**{verification.number_field: value})
            .exclude(user=user)
            .exists()
        )
        if taken:
            raise api_errors.UNIQUE.validation_error(
                "This registration number is already registered."
            )
        return value

    def validate(self, attrs):
        """Require the bar ID document of the roles that must send one."""
        verification = VERIFICATIONS[self.context["request"].user.role]
        if verification.document_required and not attrs.get("bar_id_document"):
            raise api_errors.REQUIRED.validation_error(
                {"bar_id_document": api_errors.REQUIRED.message}
            )
        return attrs


class RegistrationDocumentSerializer(serializers.Serializer):
    """The document a registration was last submitted with."""

    file_id = serializers.UUIDField()
    file_name = serializers.CharField()


class CurrentRegistrationSerializer(serializers.Serializer):
    """Body of GET /registrations/current/: what the correction screens show."""

    application_id = serializers.UUIDField()
    approval_status = serializers.ChoiceField(choices=ApprovalStatus.choices)
    role = serializers.ChoiceField(choices=Role.choices)
    officer_message = serializers.CharField(allow_blank=True)
    rejected_at = serializers.DateTimeField(allow_null=True)
    name = serializers.CharField(allow_blank=True)
    email = serializers.EmailField(allow_null=True)
    mobile_number = serializers.CharField()
    registration_number = serializers.CharField()
    document = RegistrationDocumentSerializer(allow_null=True)


class UserSerializer(serializers.ModelSerializer):
    """Read-only representation of an account."""

    class Meta:
        """Meta options."""

        model = get_user_model()
        fields = ["id", "mobile_number", "name", "email", "role", "is_active", "created_at"]
        read_only_fields = fields


class AuditUserSerializer(serializers.ModelSerializer):
    """Minimal identification of a user for audit attribution.

    Deliberately narrower than :class:`UserSerializer`: ``created_by`` /
    ``updated_by`` ride along on every audited resource, so anyone who can
    read a record would otherwise also read the mobile number and email of
    whoever touched it. An id and a display name are what attribution needs.
    """

    class Meta:
        """Meta options."""

        model = get_user_model()
        fields = ["id", "name"]
        read_only_fields = fields
