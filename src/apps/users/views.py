"""Registration and login endpoints (spec 0005 section 4)."""

from django.conf import settings
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login,
    logout,
    update_session_auth_hash,
)
from django.db import transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters
from rest_framework import status
from rest_framework.exceptions import Throttled
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AdvocateProfile, ClerkProfile, LitigantProfile, RegistrationStatus, Role
from .otp import Purpose, ResendTooSoonError, issue_otp, verify_and_consume_otp
from .serializers import (
    AdvocateRegistrationSerializer,
    ClerkRegistrationSerializer,
    MobileOTPSerializer,
    OTPRequestSerializer,
    RegistrationCompletionSerializer,
    SessionCreateSerializer,
)

OTP_BACKEND = "apps.users.backends.OTPBackend"


@method_decorator(sensitive_post_parameters("otp"), name="dispatch")
class OTPRequestView(APIView):
    """POST /auth/otp/request — send a one-time code. The only endpoint with no credential."""

    authentication_classes = []
    permission_classes = [AllowAny]

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
            raise Throttled(wait=exc.retry_after) from exc

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

    def post(self, request):
        """Create the account, or resume an unfinished one, and issue a cookie."""
        serializer = MobileOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mobile_number = serializer.validated_data["mobile_number"]

        if not verify_and_consume_otp(
            mobile_number, serializer.validated_data["otp"], Purpose.REGISTER
        ):
            return Response(
                {"detail": "Invalid or expired code."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_model = get_user_model()
        user = user_model.objects.filter(mobile_number=mobile_number).first()

        if user is None:
            user = user_model.objects.create_user(mobile_number=mobile_number)
            response_status = status.HTTP_201_CREATED
        elif user.is_registration_complete:
            return Response(
                {"detail": "Account already registered. Use POST /sessions."},
                status=status.HTTP_409_CONFLICT,
            )
        else:
            # An incomplete registration is resumable, never a lockout.
            response_status = status.HTTP_200_OK

        login(request._request, user, backend=OTP_BACKEND)

        headers = {}
        if response_status == status.HTTP_201_CREATED:
            headers["Location"] = f"/api/v1/users/{user.pk}"

        return Response(
            {
                "user_id": str(user.pk),
                "registration_status": user.registration_status,
                "next": "profile",
            },
            status=response_status,
            headers=headers,
        )


@method_decorator(sensitive_post_parameters("password", "otp"), name="dispatch")
class SessionView(APIView):
    """POST /sessions to log in, DELETE /sessions to log out."""

    authentication_classes = []
    permission_classes = [AllowAny]

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

    def delete(self, request):
        """Discard the session."""
        logout(request._request)
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
        profile_fields = data.get("profile", {})

        # The profile row and the account must never disagree about whether
        # registration finished, so both are written in one transaction.
        with transaction.atomic():
            user.name = data["name"]
            user.email = data.get("email") or None
            user.role = self.role
            user.set_password(data["password"])
            user.terms_accepted_at = timezone.now()
            user.terms_version_accepted = settings.CURRENT_TERMS_VERSION
            user.registration_status = RegistrationStatus.COMPLETE
            user.save()
            self.profile_model.objects.create(user=user, **profile_fields)

        # Setting a password rotates the session auth hash, which would log the
        # user out at the moment they finished signing up.
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
