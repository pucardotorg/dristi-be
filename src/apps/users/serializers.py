"""Request validation for the registration and login endpoints."""

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import AdvocateProfile, AdvocateType, ClerkProfile, mobile_number_validator
from .services.otp import Purpose

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
        try:
            validate_password(attrs["password"], user=candidate)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)}) from exc
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
