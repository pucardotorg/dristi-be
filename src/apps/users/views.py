"""Registration and login endpoints (spec 0005 section 4)."""

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from drf_spectacular.utils import extend_schema, extend_schema_view, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import Throttled
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.api.schema import error_responses

from . import errors
from .models import (
    PROFILE_MODELS,
    AdvocateType,
    ApprovalStatus,
    RegistrationStatus,
    Role,
)
from .serializers import (
    AdvocateRegistrationSerializer,
    ClerkRegistrationSerializer,
    CurrentRegistrationSerializer,
    CurrentUserSerializer,
    MobileOTPSerializer,
    OTPRequestSerializer,
    PasswordResetSerializer,
    RegistrationCompletionSerializer,
    RegistrationResubmissionSerializer,
    SessionCreateSerializer,
    TermsAcceptanceSerializer,
    TermsStatusSerializer,
)
from .services.otp import Purpose, ResendTooSoonError, issue_otp, verify_and_consume_otp
from .services.password import (
    get_password_reset_user,
    reset_password,
    verify_password_reset_code,
)
from .services.permissions import IsRejectedRegistrant, next_step
from .services.registration import (
    DocumentRejected,
    RegistrationNotRejected,
    complete_registration_with_document,
    describe_rejected_registration,
    resubmit_registration,
)
from .services.terms import accept_current_terms
from .tasks import schedule_registration_verification
from .verification import approval_status_of

OTP_BACKEND = "apps.users.services.backend.OTPBackend"


class OTPResendThrottled(Throttled):
    """429 for a resend inside the cooldown, worded for the person waiting.

    DRF's default reads "Request was throttled. Expected available in N
    seconds," which says nothing about what was throttled or what to do.
    """

    default_detail = errors.OTP_RESEND_TOO_SOON.message
    extra_detail_singular = "You can request another in {wait} second."
    extra_detail_plural = "You can request another in {wait} seconds."
    default_code = errors.OTP_RESEND_TOO_SOON.code


# Response shapes, declared for the OpenAPI schema only. These endpoints build
# their bodies by hand rather than through a serializer, so drf-spectacular has
# nothing to infer from and would otherwise drop them from the docs entirely.
DETAIL_RESPONSE = inline_serializer(
    name="Detail",
    fields={"detail": serializers.CharField()},
)

ACCOUNT_STATE_RESPONSE = inline_serializer(
    name="AccountState",
    fields={
        "user_id": serializers.UUIDField(),
        "registration_status": serializers.ChoiceField(choices=RegistrationStatus.choices),
        "next": serializers.CharField(allow_null=True),
    },
)

SESSION_RESPONSE = inline_serializer(
    name="SessionState",
    fields={
        "user_id": serializers.UUIDField(),
        "registration_status": serializers.ChoiceField(choices=RegistrationStatus.choices),
        "approval_status": serializers.ChoiceField(
            choices=ApprovalStatus.choices,
            allow_null=True,
            help_text="Null for roles whose registration is not approved (litigants).",
        ),
        "next": serializers.CharField(
            allow_null=True,
            help_text=(
                '"profile" to finish the wizard, "resubmit" to correct a rejected '
                'registration, "terms" to accept the current terms, or null.'
            ),
        ),
    },
)

RESUBMITTED_RESPONSE = inline_serializer(
    name="ResubmittedRegistration",
    fields={
        "application_id": serializers.UUIDField(),
        "approval_status": serializers.ChoiceField(choices=ApprovalStatus.choices),
    },
)

REGISTERED_ACCOUNT_RESPONSE = inline_serializer(
    name="RegisteredAccount",
    fields={
        "user_id": serializers.UUIDField(),
        "role": serializers.ChoiceField(choices=Role.choices),
        "registration_status": serializers.ChoiceField(choices=RegistrationStatus.choices),
        "next": serializers.CharField(allow_null=True),
    },
)

PASSWORD_RESET_VERIFIED_RESPONSE = inline_serializer(
    name="PasswordResetVerified",
    fields={
        "detail": serializers.CharField(),
        "expires_in": serializers.IntegerField(),
    },
)


# Shared by the hand-written multipart forms below.
NAME_PROPERTY = {"type": "string", "maxLength": 256}
EMAIL_PROPERTY = {"type": "string", "format": "email"}
REGISTRATION_NUMBER_PROPERTY = {"type": "string", "maxLength": 64}
BAR_ID_DOCUMENT_PROPERTY = {
    "type": "string",
    "format": "binary",
    "description": "Bar council ID as a PDF, JPEG or PNG.",
}


def _registration_form(profile_properties):
    """Return the multipart body of a registration carrying the bar ID.

    Described by hand because the serializer nests ``profile``, and a
    multipart body cannot nest: clients send ``profile.<field>`` keys, which
    is what DRF reads back into the nested serializer. Inferring from the
    serializer would document a ``profile`` object Swagger UI sends as one
    JSON string, and the file as a URI with no file picker.
    """
    required = [
        "name",
        "password",
        "terms_accepted",
        *(
            f"profile.{name}"
            for name, (_, is_required) in profile_properties.items()
            if is_required
        ),
        "bar_id_document",
    ]
    return {
        "type": "object",
        "required": required,
        "properties": {
            "name": NAME_PROPERTY,
            "email": EMAIL_PROPERTY,
            "password": {"type": "string", "format": "password", "maxLength": 128},
            "terms_accepted": {"type": "boolean"},
            **{f"profile.{name}": schema for name, (schema, _) in profile_properties.items()},
            "bar_id_document": BAR_ID_DOCUMENT_PROPERTY,
        },
    }


ADVOCATE_REGISTRATION_FORM = _registration_form(
    {
        "bar_registration_id": (REGISTRATION_NUMBER_PROPERTY, True),
        "advocate_type": ({"type": "string", "enum": AdvocateType.values}, False),
    },
)

CLERK_REGISTRATION_FORM = _registration_form(
    {"clerk_registration_number": (REGISTRATION_NUMBER_PROPERTY, True)},
)

# Described by hand for the same reason as the registration forms: inferred
# from the serializer, the document is a URI string with no file picker.
RESUBMISSION_FORM = {
    "type": "object",
    "required": ["name", "registration_number", "bar_id_document"],
    "properties": {
        "name": NAME_PROPERTY,
        "email": EMAIL_PROPERTY,
        "registration_number": REGISTRATION_NUMBER_PROPERTY,
        "bar_id_document": BAR_ID_DOCUMENT_PROPERTY,
    },
}


@method_decorator(sensitive_post_parameters("otp"), name="dispatch")
class OTPRequestView(APIView):
    """POST /auth/otp/request — send a one-time code. The only endpoint with no credential."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = OTPRequestSerializer

    @extend_schema(
        tags=["auth"],
        responses={
            202: DETAIL_RESPONSE,
            **error_responses(
                errors.OTP_RESEND_TOO_SOON.example(
                    "A code was already sent to this number. You can request another in 25 seconds."
                )
            ),
        },
    )
    def post(self, request):
        """Issue a code, or refuse with the seconds remaining on the cooldown."""
        serializer = OTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            issue_otp(
                serializer.validated_data["mobile_number"],
                serializer.validated_data["purpose"],
            )
        except ResendTooSoonError as exc:
            # DRF's exception handler turns this into 429 + Retry-After.
            raise OTPResendThrottled(wait=exc.retry_after) from exc

        # The response must not reveal whether the number belongs to an account.
        return Response(
            {"detail": "If the number is valid, a code has been sent."},
            status=status.HTTP_202_ACCEPTED,
        )


@method_decorator(sensitive_post_parameters("otp"), name="dispatch")
class UserCreateView(APIView):
    """POST /users — create or resume an account. The OTP is the credential."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = MobileOTPSerializer

    @extend_schema(
        tags=["auth"],
        responses={
            201: ACCOUNT_STATE_RESPONSE,
            200: ACCOUNT_STATE_RESPONSE,
            **error_responses(errors.OTP_INVALID, errors.ACCOUNT_ALREADY_REGISTERED),
        },
    )
    def post(self, request):
        """Create the account, or resume an unfinished one, and issue a cookie."""
        serializer = MobileOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mobile_number = serializer.validated_data["mobile_number"]

        if not verify_and_consume_otp(
            mobile_number, serializer.validated_data["otp"], Purpose.REGISTER
        ):
            raise BusinessError(errors.OTP_INVALID)

        user_model = get_user_model()
        user = user_model.objects.filter(mobile_number=mobile_number).first()

        if user is None:
            user = user_model.objects.create_user(mobile_number=mobile_number)
            response_status = status.HTTP_201_CREATED
        elif user.is_registration_complete:
            raise BusinessError(errors.ACCOUNT_ALREADY_REGISTERED)
        else:
            # An incomplete registration is resumable, never a lockout.
            response_status = status.HTTP_200_OK

        login(request._request, user, backend=OTP_BACKEND)

        # No Location header. Spec 4.1 shows one, but nothing in this project
        # serves a user detail route, so the header pointed at a 404 — worse
        # than its absence, since a client that follows it learns nothing and
        # a client that does not is unaffected. `user_id` in the body is what
        # callers actually use. Restore it alongside a GET /users/<id>/, not
        # before.
        return Response(
            {
                "user_id": str(user.pk),
                "registration_status": user.registration_status,
                "next": "profile",
            },
            status=response_status,
        )


@method_decorator(sensitive_post_parameters("password", "otp"), name="dispatch")
class SessionView(APIView):
    """POST /sessions to log in, DELETE /sessions to log out."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = SessionCreateSerializer

    @extend_schema(
        tags=["auth"],
        responses={
            200: SESSION_RESPONSE,
            **error_responses(
                errors.CREDENTIAL_CHOICE, errors.INVALID_CREDENTIALS, errors.APPROVAL_PENDING
            ),
        },
    )
    def post(self, request):
        """Authenticate by OTP or password and issue a session cookie."""
        serializer = SessionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        credentials = serializer.validated_data

        # Both backends are tried in order, so one call covers either credential.
        user = authenticate(
            request._request,
            mobile_number=credentials["mobile_number"],
            otp=credentials.get("otp"),
            password=credentials.get("password"),
            purpose=Purpose.LOGIN,
        )
        if user is None:
            raise BusinessError(errors.INVALID_CREDENTIALS)

        # Checked before `login`, so a pending advocate or clerk gets no session.
        approval_status = approval_status_of(user)
        if approval_status == ApprovalStatus.PENDING:
            raise BusinessError(errors.APPROVAL_PENDING)

        # A rejected advocate or clerk does get one: the rejection SMS sends
        # them here to read the reason and resubmit. IsNotAwaitingApproval keeps
        # that session to the resubmission endpoints.
        login(request._request, user)

        # An incomplete account, a rejected one, or one that has not accepted
        # the current terms can still log in; the client needs to know so it
        # can route to the right screen instead of failing against every gated
        # endpoint.
        return Response(
            {
                "user_id": str(user.pk),
                "registration_status": user.registration_status,
                "approval_status": approval_status,
                "next": next_step(user),
            }
        )

    @extend_schema(tags=["auth"], request=None, responses={204: None})
    def delete(self, request):
        """Discard the session."""
        logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(sensitive_post_parameters("otp"), name="dispatch")
class PasswordResetVerifyView(APIView):
    """POST /auth/password-reset/verify — prove control of the number. Logs nobody in."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = MobileOTPSerializer

    @extend_schema(
        tags=["auth"],
        responses={
            200: PASSWORD_RESET_VERIFIED_RESPONSE,
            **error_responses(errors.OTP_INVALID),
        },
    )
    def post(self, request):
        """Consume a password_reset code and allow this session to set a password."""
        serializer = MobileOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not verify_password_reset_code(
            request.session,
            serializer.validated_data["mobile_number"],
            serializer.validated_data["otp"],
        ):
            raise BusinessError(errors.OTP_INVALID)

        return Response(
            {
                "detail": "Code verified. Set a new password.",
                "expires_in": settings.PASSWORD_RESET_WINDOW_SECONDS,
            }
        )


@method_decorator(sensitive_post_parameters("new_password"), name="dispatch")
class PasswordResetView(APIView):
    """POST /auth/password-reset — set a new password after verification."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = PasswordResetSerializer

    @extend_schema(
        tags=["auth"],
        responses={
            204: None,
            **error_responses(
                errors.PASSWORD_REJECTED.example(
                    "This password is too short. It must contain at least 8 characters.",
                    field="new_password",
                ),
                errors.PASSWORD_RESET_NOT_VERIFIED,
            ),
        },
    )
    def post(self, request):
        """Set the password once, then require a fresh login with it."""
        user = get_password_reset_user(request.session)
        if user is None:
            raise BusinessError(errors.PASSWORD_RESET_NOT_VERIFIED)

        serializer = PasswordResetSerializer(data=request.data, context={"user": user})
        serializer.is_valid(raise_exception=True)

        reset_password(request.session, user, serializer.validated_data["new_password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentUserView(APIView):
    """GET /users/me — the logged-in user's account and profile.

    Gated on IsAuthenticated alone: a client resuming an unfinished
    registration needs to read the account to know where it left off.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["users"], responses={200: CurrentUserSerializer})
    def get(self, request):
        """Return the caller's account with the profile for their role."""
        return Response(CurrentUserSerializer(request.user).data)


class TermsView(APIView):
    """POST /users/me/terms — accept the terms in force.

    The way in for accounts that never passed through the wizard, such as those
    created through filing, and for every account once the terms are revised.

    Gated on IsAuthenticated alone: this is the endpoint that satisfies
    HasAcceptedCurrentTerms, so it cannot require it.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TermsAcceptanceSerializer

    @extend_schema(
        tags=["users"],
        responses={
            200: TermsStatusSerializer,
            **error_responses(errors.TERMS_NOT_ACCEPTED.example(field="terms_accepted")),
        },
    )
    def post(self, request):
        """Record acceptance of the version in force. Repeating it changes nothing."""
        serializer = TermsAcceptanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        accept_current_terms(request.user)
        return Response(TermsStatusSerializer(request.user).data)


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class BaseRegistrationCompletionView(APIView):
    """Shared body of POST /litigants, /advocates and /clerks.

    Deliberately gated on IsAuthenticated alone: these are the endpoints that
    grant a complete registration, so they cannot require one.
    """

    permission_classes = [IsAuthenticated]

    role = None
    serializer_class = RegistrationCompletionSerializer

    @extend_schema(
        tags=["registration"],
        responses={
            201: REGISTERED_ACCOUNT_RESPONSE,
            **error_responses(
                errors.EMAIL_TAKEN.example(field="email"),
                errors.TERMS_NOT_ACCEPTED.example(field="terms_accepted"),
                errors.PASSWORD_REJECTED.example(
                    "This password is too short. It must contain at least 8 characters.",
                    field="password",
                ),
                errors.REGISTRATION_ALREADY_COMPLETE,
            ),
        },
    )
    def post(self, request):
        """Write the profile and the account state as one unit."""
        user = request.user
        if user.is_registration_complete:
            raise BusinessError(errors.REGISTRATION_ALREADY_COMPLETE)

        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            _, file_id = complete_registration_with_document(
                user=user,
                document=data.get("bar_id_document"),
                role=self.role,
                profile_model=PROFILE_MODELS[self.role],
                name=data["name"],
                password=data["password"],
                email=data.get("email"),
                profile_fields=data.get("profile", {}),
            )
        except DocumentRejected as exc:
            raise serializers.ValidationError({"bar_id_document": exc.messages}) from exc

        # Verification is raised in the background so a slow or failing
        # request flow never fails a registration that has already committed.
        schedule_registration_verification(user, file_id)

        if approval_status_of(user) == ApprovalStatus.PENDING:
            logout(request._request)
        else:
            update_session_auth_hash(request._request, user)

        return Response(
            {
                "user_id": str(user.pk),
                "role": user.role,
                "registration_status": user.registration_status,
                "next": None,
            },
            status=status.HTTP_201_CREATED,
        )


class LitigantRegistrationView(BaseRegistrationCompletionView):
    """POST /litigants."""

    role = Role.LITIGANT


@extend_schema_view(
    post=extend_schema(request={"multipart/form-data": ADVOCATE_REGISTRATION_FORM}),
)
class AdvocateRegistrationView(BaseRegistrationCompletionView):
    """POST /advocates.

    Multipart only: the bar ID document is required, and a JSON body cannot
    carry it. The nested profile is sent as ``profile.<field>`` form keys.
    """

    role = Role.ADVOCATE
    serializer_class = AdvocateRegistrationSerializer
    parser_classes = [MultiPartParser, FormParser]


@extend_schema_view(
    post=extend_schema(request={"multipart/form-data": CLERK_REGISTRATION_FORM}),
)
class ClerkRegistrationView(BaseRegistrationCompletionView):
    """POST /clerks.

    Multipart only, like POST /advocates: the bar ID document is required.
    """

    role = Role.CLERK
    serializer_class = ClerkRegistrationSerializer
    parser_classes = [MultiPartParser, FormParser]


class CurrentRegistrationView(APIView):
    """GET /registrations/current/ — the rejected registration to correct.

    Feeds the correction screens: the application id, the approver's reason
    and the claim as last submitted, to pre-fill the steps.
    """

    permission_classes = [IsAuthenticated, IsRejectedRegistrant]

    @extend_schema(
        tags=["registration"],
        responses={
            200: CurrentRegistrationSerializer,
            **error_responses(errors.NOTHING_TO_RESUBMIT),
        },
    )
    def get(self, request):
        """Return the rejected registration with the approver's reason."""
        try:
            registration = describe_rejected_registration(request.user)
        except RegistrationNotRejected as exc:
            raise BusinessError(errors.NOTHING_TO_RESUBMIT) from exc
        return Response(CurrentRegistrationSerializer(registration).data)


class RegistrationResubmitView(APIView):
    """POST /registrations/current/resubmit/ — send the corrected claim back.

    The same application goes back for approval: the request keeps its id and
    only its version moves on. Multipart when it carries the bar ID document.
    """

    permission_classes = [IsAuthenticated, IsRejectedRegistrant]

    @extend_schema(
        tags=["registration"],
        request={
            "multipart/form-data": RESUBMISSION_FORM,
            "application/json": RegistrationResubmissionSerializer,
        },
        responses={
            200: RESUBMITTED_RESPONSE,
            **error_responses(
                api_errors.REQUIRED.example(field="name"),
                api_errors.UNIQUE.example(
                    "This registration number is already registered.", field="registration_number"
                ),
                errors.EMAIL_TAKEN.example(field="email"),
                errors.NOTHING_TO_RESUBMIT,
            ),
        },
    )
    def post(self, request):
        """Apply the corrections, resubmit, and end the session."""
        serializer = RegistrationResubmissionSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            resubmitted = resubmit_registration(
                user=request.user,
                name=data["name"],
                email=data.get("email"),
                registration_number=data["registration_number"],
                document=data.get("bar_id_document"),
            )
        except DocumentRejected as exc:
            raise serializers.ValidationError({"bar_id_document": exc.messages}) from exc
        except RegistrationNotRejected as exc:
            raise BusinessError(errors.NOTHING_TO_RESUBMIT) from exc

        # Back to PENDING, and a pending account holds no session (see
        # SessionView). The client shows the awaiting-approval screen.
        logout(request._request)
        return Response(
            {"application_id": str(resubmitted.pk), "approval_status": ApprovalStatus.PENDING}
        )
