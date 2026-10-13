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
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import Throttled
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AdvocateProfile, ClerkProfile, LitigantProfile, RegistrationStatus, Role
from .serializers import (
    AdvocateRegistrationSerializer,
    ClerkRegistrationSerializer,
    MobileOTPSerializer,
    OTPRequestSerializer,
    PasswordResetSerializer,
    RegistrationCompletionSerializer,
    SessionCreateSerializer,
)
from .services.otp import Purpose, ResendTooSoonError, issue_otp, verify_and_consume_otp
from .services.password import (
    get_password_reset_user,
    reset_password,
    verify_password_reset_code,
)
from .services.registration import complete_registration

OTP_BACKEND = "apps.users.services.backend.OTPBackend"


class OTPResendThrottled(Throttled):
    """429 for a resend inside the cooldown, worded for the person waiting.

    DRF's default reads "Request was throttled. Expected available in N
    seconds," which says nothing about what was throttled or what to do.
    """

    default_detail = "A code was already sent to this number."
    extra_detail_singular = "You can request another in {wait} second."
    extra_detail_plural = "You can request another in {wait} seconds."
    default_code = "otp_resend_too_soon"


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

INVALID_CODE_DETAIL = "Invalid or expired code."


@method_decorator(sensitive_post_parameters("otp"), name="dispatch")
class OTPRequestView(APIView):
    """POST /auth/otp/request — send a one-time code. The only endpoint with no credential."""

    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = OTPRequestSerializer

    @extend_schema(tags=["auth"], responses={202: DETAIL_RESPONSE})
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
            401: DETAIL_RESPONSE,
            409: DETAIL_RESPONSE,
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
            return Response(
                {"detail": INVALID_CODE_DETAIL},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_model = get_user_model()
        user = user_model.objects.filter(mobile_number=mobile_number).first()

        if user is None:
            user = user_model.objects.create_user(mobile_number=mobile_number)
            response_status = status.HTTP_201_CREATED
        elif user.is_registration_complete:
            return Response(
                {"detail": "Account already registered with this mobile number."},
                status=status.HTTP_409_CONFLICT,
            )
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
        responses={200: ACCOUNT_STATE_RESPONSE, 401: DETAIL_RESPONSE},
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
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        login(request._request, user)

        # An incomplete account can log in; the client needs to know so it can
        # route to the wizard instead of failing against every gated endpoint.
        return Response(
            {
                "user_id": str(user.pk),
                "registration_status": user.registration_status,
                "next": None if user.is_registration_complete else "profile",
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
        responses={200: PASSWORD_RESET_VERIFIED_RESPONSE, 401: DETAIL_RESPONSE},
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
            return Response(
                {"detail": INVALID_CODE_DETAIL},
                status=status.HTTP_401_UNAUTHORIZED,
            )

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

    @extend_schema(tags=["auth"], responses={204: None, 401: DETAIL_RESPONSE})
    def post(self, request):
        """Set the password once, then require a fresh login with it."""
        user = get_password_reset_user(request.session)
        if user is None:
            return Response(
                {"detail": "Verify a password reset code first, or request a new one."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = PasswordResetSerializer(data=request.data, context={"user": user})
        serializer.is_valid(raise_exception=True)

        reset_password(request.session, user, serializer.validated_data["new_password"])
        return Response(status=status.HTTP_204_NO_CONTENT)


@method_decorator(sensitive_post_parameters("password"), name="dispatch")
class BaseRegistrationCompletionView(APIView):
    """Shared body of POST /litigants, /advocates and /clerks.

    Deliberately gated on IsAuthenticated alone: these are the endpoints that
    grant a complete registration, so they cannot require one.
    """

    permission_classes = [IsAuthenticated]

    role = None
    profile_model = None
    serializer_class = RegistrationCompletionSerializer

    @extend_schema(
        tags=["registration"],
        responses={201: REGISTERED_ACCOUNT_RESPONSE, 409: DETAIL_RESPONSE},
    )
    def post(self, request):
        """Write the profile and the account state as one unit."""
        user = request.user
        if user.is_registration_complete:
            return Response(
                {"detail": "Registration is already complete."},
                status=status.HTTP_409_CONFLICT,
            )

        serializer = self.serializer_class(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        complete_registration(
            user=user,
            role=self.role,
            profile_model=self.profile_model,
            name=data["name"],
            password=data["password"],
            email=data.get("email"),
            profile_fields=data.get("profile", {}),
        )

        # Session handling stays in the view: setting a password rotates the
        # session auth hash, which would log the user out at the moment they
        # finished signing up.
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
    profile_model = LitigantProfile


class AdvocateRegistrationView(BaseRegistrationCompletionView):
    """POST /advocates."""

    role = Role.ADVOCATE
    profile_model = AdvocateProfile
    serializer_class = AdvocateRegistrationSerializer


class ClerkRegistrationView(BaseRegistrationCompletionView):
    """POST /clerks."""

    role = Role.CLERK
    profile_model = ClerkProfile
    serializer_class = ClerkRegistrationSerializer
