"""Endpoint tests for registration and login (spec 0005 section 4)."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import override_settings
from django.urls import path, reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.users.models import (
    AdvocateProfile,
    ClerkProfile,
    LitigantProfile,
    RegistrationStatus,
    Role,
    User,
)
from apps.users.services.otp import Purpose
from config.urls import urlpatterns as project_urlpatterns

from .base import MOBILE, PASSWORD, OTPTestCase


class OTPRequestTests(OTPTestCase):
    """POST /auth/otp/request."""

    def test_code_is_sent(self):
        """A first request sends a code of the configured length."""
        code = self.request_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_response_does_not_reveal_account_existence(self):
        """The body is identical whether or not the number has an account."""
        User.objects.create_user(mobile_number=MOBILE)
        with patch("apps.users.services.otp._send_sms"):
            known = self.client.post(
                reverse("otp-request"), {"mobile_number": MOBILE}, format="json"
            )
        cache.clear()
        with patch("apps.users.services.otp._send_sms"):
            unknown = self.client.post(
                reverse("otp-request"), {"mobile_number": "+919000000000"}, format="json"
            )
        # Compare the payload only: the renderer stamps a `meta.timestamp` that
        # differs between any two responses and reveals nothing.
        self.assertEqual(known.json()["detail"], unknown.json()["detail"])
        self.assertEqual(known.status_code, unknown.status_code)

    def test_resend_inside_cooldown_is_refused(self):
        """A second request inside the window returns 429 with Retry-After."""
        self.request_code()
        with patch("apps.users.services.otp._send_sms") as send:
            response = self.client.post(
                reverse("otp-request"), {"mobile_number": MOBILE}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertIn("Retry-After", response)
        self.assertGreaterEqual(int(response["Retry-After"]), 1)
        send.assert_not_called()

    def test_cooldown_is_per_number(self):
        """A cooldown on one number does not block another."""
        self.request_code()
        with patch("apps.users.services.otp._send_sms") as send:
            response = self.client.post(
                reverse("otp-request"), {"mobile_number": "+919000000000"}, format="json"
            )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        send.assert_called_once()

    @override_settings(OTP_RESEND_COOLDOWN_SECONDS=900)
    def test_cooldown_is_read_from_settings_per_request(self):
        """Changing the setting changes the window without a code change."""
        self.request_code()
        response = self.client.post(
            reverse("otp-request"), {"mobile_number": MOBILE}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertGreater(int(response["Retry-After"]), 800)

    def test_malformed_number_is_rejected(self):
        """A number that is not in international format is refused."""
        response = self.client.post(
            reverse("otp-request"), {"mobile_number": "9876543210"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UserCreateTests(OTPTestCase):
    """POST /users."""

    def test_new_account_is_created(self):
        """A valid code creates the account and issues a cookie."""
        response = self.create_account()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        body = response.json()
        self.assert_meta(body)
        self.assertEqual(body["registration_status"], RegistrationStatus.PENDING_PROFILE)
        self.assertEqual(body["next"], "profile")
        self.assertIn("Location", response)
        self.assertIn("sessionid", response.cookies)

        user = User.objects.get(mobile_number=MOBILE)
        self.assertFalse(user.has_usable_password())

    def test_invalid_code_is_rejected(self):
        """A wrong code creates nothing."""
        self.request_code()
        response = self.client.post(
            reverse("user-create"),
            {"mobile_number": MOBILE, "otp": "000000"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(User.objects.filter(mobile_number=MOBILE).exists())

    def test_abandoned_registration_is_resumable(self):
        """A second run against an incomplete account resumes it with a 200."""
        self.create_account()
        self.client.logout()

        # The user comes back later, so the resend cooldown has lapsed.
        cache.clear()

        response = self.create_account()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(mobile_number=MOBILE).count(), 1)

    def test_complete_account_is_refused(self):
        """A finished account is told to use POST /sessions."""
        User.objects.create_user(
            mobile_number=MOBILE,
            registration_status=RegistrationStatus.COMPLETE,
        )
        response = self.create_account()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_otp_is_never_echoed(self):
        """The response body contains no trace of the credential."""
        code = self.request_code()
        response = self.client.post(
            reverse("user-create"),
            {"mobile_number": MOBILE, "otp": code},
            format="json",
        )
        self.assertNotIn(code, response.content.decode())


class RegistrationCompletionTests(OTPTestCase):
    """POST /litigants, /advocates and /clerks."""

    def setUp(self):
        """Create an account sitting at PENDING_PROFILE, already logged in."""
        super().setUp()
        self.create_account()
        self.user = User.objects.get(mobile_number=MOBILE)

    def body(self, **extra):
        """Return a valid completion body."""
        return {
            "name": "Asha Menon",
            "email": "asha@example.com",
            "password": PASSWORD,
            "terms_accepted": True,
            **extra,
        }

    def test_litigant_completes(self):
        """A litigant gets a profile, a role and COMPLETE status."""
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.user.refresh_from_db()
        self.assertEqual(self.user.registration_status, RegistrationStatus.COMPLETE)
        self.assertEqual(self.user.role, Role.LITIGANT)
        self.assertTrue(self.user.check_password(PASSWORD))
        self.assertTrue(LitigantProfile.objects.filter(user=self.user).exists())

    def test_advocate_completes_with_profile(self):
        """The nested profile is written to the advocate table."""
        response = self.client.post(
            reverse("advocate-create"),
            self.body(profile={"bar_registration_id": "KER/1234/2019"}),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            AdvocateProfile.objects.get(user=self.user).bar_registration_id,
            "KER/1234/2019",
        )

    def test_clerk_completes_with_profile(self):
        """The nested profile is written to the clerk table."""
        response = self.client.post(
            reverse("clerk-create"),
            self.body(profile={"clerk_registration_number": "CLK/99/2020"}),
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            ClerkProfile.objects.get(user=self.user).clerk_registration_number,
            "CLK/99/2020",
        )

    def test_advocate_requires_profile(self):
        """A missing profile block is a 400, and nothing is written."""
        response = self.client.post(reverse("advocate-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.user.refresh_from_db()
        self.assertEqual(self.user.registration_status, RegistrationStatus.PENDING_PROFILE)

    def test_terms_must_be_accepted(self):
        """A false acceptance rejects the registration rather than warning."""
        response = self.client.post(
            reverse("litigant-create"), self.body(terms_accepted=False), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.user.refresh_from_db()
        self.assertEqual(self.user.registration_status, RegistrationStatus.PENDING_PROFILE)

    @override_settings(CURRENT_TERMS_VERSION=7)
    def test_terms_version_comes_from_the_server(self):
        """A client-supplied version is ignored in favour of server config."""
        response = self.client.post(
            reverse("litigant-create"), self.body(terms_version=999), format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        self.user.refresh_from_db()
        self.assertEqual(self.user.terms_version_accepted, 7)
        self.assertIsNotNone(self.user.terms_accepted_at)

    def test_completing_twice_is_refused(self):
        """A finished registration cannot be overwritten."""
        self.client.post(reverse("litigant-create"), self.body(), format="json")
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_session_survives_the_password_being_set(self):
        """The user is still logged in immediately after completing."""
        self.client.post(reverse("litigant-create"), self.body(), format="json")
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)  # not 403

    def test_anonymous_caller_is_refused(self):
        """Completion requires the session issued by POST /users."""
        self.client.logout()
        response = self.client.post(reverse("litigant-create"), self.body(), format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class SessionTests(OTPTestCase):
    """POST /sessions."""

    def setUp(self):
        """Create a fully registered account."""
        super().setUp()
        self.user = User.objects.create_user(
            mobile_number=MOBILE,
            password=PASSWORD,
            name="Asha Menon",
            role=Role.LITIGANT,
            registration_status=RegistrationStatus.COMPLETE,
        )
        self.client.logout()

    def test_login_with_password(self):
        """Mobile plus password issues a session."""
        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["registration_status"], RegistrationStatus.COMPLETE)
        self.assertIsNone(response.json()["next"])

    def test_login_with_otp(self):
        """Mobile plus a login-purpose code issues a session."""
        code = self.request_code(purpose=Purpose.LOGIN)
        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "otp": code},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_wrong_password_is_refused(self):
        """A bad password issues nothing."""
        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": "wrong-password"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_exactly_one_credential_is_required(self):
        """Neither zero credentials nor both are accepted."""
        for body in (
            {"mobile_number": MOBILE},
            {"mobile_number": MOBILE, "otp": "1", "password": "x"},
        ):
            response = self.client.post(reverse("session"), body, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_incomplete_account_can_log_in_and_is_told_so(self):
        """A PENDING_PROFILE account logs in, and the body routes it to the wizard."""
        self.user.registration_status = RegistrationStatus.PENDING_PROFILE
        self.user.save()

        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["next"], "profile")

    def test_logout_discards_the_session(self):
        """DELETE /sessions clears the cookie."""
        self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": PASSWORD},
            format="json",
        )
        response = self.client.delete(reverse("session"))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class GatedProbeView(APIView):
    """An endpoint that declares no permissions, so it inherits the defaults.

    Defined here rather than borrowing one from another app: what is under test
    is this project's DEFAULT_PERMISSION_CLASSES, and the test should not break
    when some other app retires an endpoint.
    """

    def get(self, request):
        """Return 200 to any caller the default permissions let through."""
        return Response({"ok": True})


# The project's real routes plus the probe, so tests can use both.
urlpatterns = [
    *project_urlpatterns,
    path("gated-probe/", GatedProbeView.as_view(), name="gated-probe"),
]


@override_settings(ROOT_URLCONF=__name__)
class GateTests(OTPTestCase):
    """The default permission classes."""

    def test_anonymous_caller_is_refused(self):
        """No session at all fails the IsAuthenticated half of the default."""
        response = self.client.get(reverse("gated-probe"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_incomplete_account_is_gated(self):
        """A valid session for an unfinished account is still refused."""
        self.create_account()
        response = self.client.get(reverse("gated-probe"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_complete_account_passes(self):
        """A finished account reaches the same endpoint."""
        user = User.objects.create_user(
            mobile_number=MOBILE,
            password=PASSWORD,
            registration_status=RegistrationStatus.COMPLETE,
        )
        self.client.force_authenticate(user=user)
        response = self.client.get(reverse("gated-probe"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ResponseEnvelopeTests(OTPTestCase):
    """Every endpoint carries the meta envelope (spec 0000 section 8)."""

    def test_otp_request_carries_meta(self):
        """POST /auth/otp/request/ returns the envelope."""
        with patch("apps.users.services.otp._send_sms"):
            response = self.client.post(
                reverse("otp-request"), {"mobile_number": MOBILE}, format="json"
            )
        self.assert_meta(response.json())

    def test_user_create_carries_meta(self):
        """POST /users/ returns the envelope."""
        self.assert_meta(self.create_account().json())

    def test_session_carries_meta(self):
        """POST /sessions/ returns the envelope."""
        User.objects.create_user(
            mobile_number=MOBILE,
            password=PASSWORD,
            registration_status=RegistrationStatus.COMPLETE,
        )
        response = self.client.post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": PASSWORD},
            format="json",
        )
        self.assert_meta(response.json())

    def test_registration_completion_carries_meta(self):
        """POST /litigants/ returns the envelope."""
        self.create_account()
        response = self.client.post(
            reverse("litigant-create"),
            {
                "name": "Asha Menon",
                "password": PASSWORD,
                "terms_accepted": True,
            },
            format="json",
        )
        self.assert_meta(response.json())

    def test_error_responses_carry_meta(self):
        """The envelope is present on failures too, not only success."""
        response = self.client.post(
            reverse("otp-request"), {"mobile_number": "not-a-number"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assert_meta(response.json())
