"""Request validation for the registration and login endpoints."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import PolymorphicProxySerializer, extend_schema_field
from rest_framework import serializers

from .models import (
    AdvocateProfile,
    AdvocateType,
    ClerkProfile,
    LitigantProfile,
    mobile_number_validator,
)
from .services.otp import Purpose
from .services.permissions import next_step

MAX_PASSWORD_LENGTH = 128


def run_password_validators(field, password, user):
    """Run AUTH_PASSWORD_VALIDATORS, reporting failures under `field`."""
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({field: list(exc.messages)}) from exc


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
            raise serializers.ValidationError("Provide exactly one of otp or password.")
        return attrs


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
        run_password_validators("password", attrs["password"], candidate)
        return attrs

    def validate_email(self, value):
        """Reject an email already claimed by another account."""
        if not value:
            return None
        current = self.context["request"].user
        taken = get_user_model().objects.filter(email__iexact=value).exclude(pk=current.pk).exists()
        if taken:
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_terms_accepted(self, value):
        """A missing or false acceptance rejects the registration."""
        if not value:
            raise serializers.ValidationError("The terms must be accepted to register.")
        return value


class TermsAcceptanceSerializer(serializers.Serializer):
    """Body of POST /users/me/terms.

    As with registration, `terms_version` is deliberately not declared: what was
    accepted is whatever the server has in force, never what the client says.
    """

    terms_accepted = serializers.BooleanField()

    def validate_terms_accepted(self, value):
        """A missing or false acceptance is refused rather than recorded."""
        if not value:
            raise serializers.ValidationError("The terms must be accepted to continue.")
        return value


class TermsStatusSerializer(serializers.ModelSerializer):
    """Response of POST /users/me/terms: where the account stands on the terms."""

    current_terms_version = serializers.SerializerMethodField()
    has_current_terms = serializers.BooleanField(read_only=True)
    next = serializers.SerializerMethodField()

    class Meta:
        """Meta options."""

        model = get_user_model()
        fields = [
            "current_terms_version",
            "terms_version_accepted",
            "terms_accepted_at",
            "has_current_terms",
            "next",
        ]
        read_only_fields = fields

    def get_current_terms_version(self, user) -> int:
        """The version in force."""
        return settings.CURRENT_TERMS_VERSION

    def get_next(self, user) -> str | None:
        """Where the client should send the user next, or None."""
        return next_step(user)


class PasswordResetSerializer(serializers.Serializer):
    """Body of POST /auth/password-reset. The verified session is the credential."""

    new_password = serializers.CharField(max_length=MAX_PASSWORD_LENGTH, write_only=True)

    def validate(self, attrs):
        """Run the password through AUTH_PASSWORD_VALIDATORS against the account."""
        run_password_validators("new_password", attrs["new_password"], self.context["user"])
        return attrs


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
    """Body of POST /advocates."""

    profile = AdvocateProfileSerializer()


class ClerkRegistrationSerializer(RegistrationCompletionSerializer):
    """Body of POST /clerks."""

    profile = ClerkProfileSerializer()


class UserSerializer(serializers.ModelSerializer):
    """Read-only representation of an account."""

    class Meta:
        """Meta options."""

        model = get_user_model()
        fields = ["id", "mobile_number", "name", "email", "role", "is_active", "created_at"]
        read_only_fields = fields


class LitigantProfileReadSerializer(serializers.ModelSerializer):
    """A litigant's profile as returned by GET /users/me."""

    class Meta:
        """Meta options."""

        model = LitigantProfile
        fields = ["id", "created_at", "updated_at"]
        read_only_fields = fields


class AdvocateProfileReadSerializer(serializers.ModelSerializer):
    """An advocate's profile as returned by GET /users/me."""

    class Meta:
        """Meta options."""

        model = AdvocateProfile
        fields = [
            "id",
            "bar_registration_id",
            "advocate_type",
            "approval_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ClerkProfileReadSerializer(serializers.ModelSerializer):
    """An advocate clerk's profile as returned by GET /users/me."""

    class Meta:
        """Meta options."""

        model = ClerkProfile
        fields = [
            "id",
            "clerk_registration_number",
            "approval_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


PROFILE_SERIALIZERS = {
    LitigantProfile: LitigantProfileReadSerializer,
    AdvocateProfile: AdvocateProfileReadSerializer,
    ClerkProfile: ClerkProfileReadSerializer,
}


class CurrentUserSerializer(serializers.ModelSerializer):
    """Body of GET /users/me: the caller's account plus their role's profile.

    `profile` is null until registration completes, and for a role that has
    no profile table. The display name lives on the account only.
    """

    has_current_terms = serializers.BooleanField(read_only=True)
    profile = serializers.SerializerMethodField()

    class Meta:
        """Meta options."""

        model = get_user_model()
        fields = [
            "id",
            "mobile_number",
            "name",
            "email",
            "role",
            "registration_status",
            "terms_accepted_at",
            "terms_version_accepted",
            "has_current_terms",
            "created_at",
            "profile",
        ]
        read_only_fields = fields

    @extend_schema_field(
        PolymorphicProxySerializer(
            component_name="Profile",
            serializers=list(PROFILE_SERIALIZERS.values()),
            resource_type_field_name=None,
            allow_null=True,
        )
    )
    def get_profile(self, user):
        """Serialize the profile matching the user's role, or None."""
        profile = user.profile
        if profile is None:
            return None
        return PROFILE_SERIALIZERS[type(profile)](profile).data


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
