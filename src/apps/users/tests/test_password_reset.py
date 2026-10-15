"""Forgotten-password reset: verify a code, then set the password."""

import time

from django.contrib.auth import get_user
from django.http import HttpRequest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.users.models import RegistrationStatus, Role, User
from apps.users.services.otp import Purpose
from apps.users.services.password import SESSION_KEY

from .base import MOBILE, PASSWORD, OTPTestCase

NEW_PASSWORD = "another-sufficiently-long-passphrase"


class PasswordResetTests(OTPTestCase):
    """POST /auth/password-reset/verify and POST /auth/password-reset."""

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

    def verify(self, code, mobile_number=MOBILE):
        """Submit a code to the verify step."""
        return self.client.post(
            reverse("password-reset-verify"),
            {"mobile_number": mobile_number, "otp": code},
            format="json",
        )

    def reset(self, new_password=NEW_PASSWORD, client=None):
        """Submit a new password to the reset step."""
        return (client or self.client).post(
            reverse("password-reset"),
            {"new_password": new_password},
            format="json",
        )

    def verified(self):
        """Request and verify a reset code, leaving the session allowed to reset."""
        response = self.verify(self.request_code(purpose=Purpose.PASSWORD_RESET))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response

    def login(self, password, client=None):
        """Attempt a password login."""
        return (client or self.client).post(
            reverse("session"),
            {"mobile_number": MOBILE, "password": password},
            format="json",
        )

    def test_full_flow_sets_the_new_password(self):
        """Verify then reset: the new password works and the old one does not."""
        self.assertEqual(self.verified().json()["expires_in"], 600)
        self.assertNotIn("_auth_user_id", self.client.session)

        self.assertEqual(self.reset().status_code, status.HTTP_204_NO_CONTENT)

        self.assertEqual(self.login(PASSWORD).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.login(NEW_PASSWORD).status_code, status.HTTP_200_OK)

    def test_login_code_cannot_open_a_reset(self):
        """Only a password_reset-purpose code verifies."""
        code = self.request_code(purpose=Purpose.LOGIN)
        self.assertEqual(self.verify(code).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reset_without_verification_is_refused(self):
        """The reset step needs the verify step first."""
        self.assertEqual(self.reset().status_code, status.HTTP_401_UNAUTHORIZED)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(PASSWORD))

    def test_verification_is_bound_to_the_session(self):
        """Another client cannot use a session it did not verify in."""
        self.verified()
        self.assertEqual(self.reset(client=APIClient()).status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reset_works_only_once(self):
        """A verified session sets one password, not several."""
        self.verified()
        self.reset()
        self.assertEqual(self.reset().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_reset_after_the_window_is_refused(self):
        """The verification expires."""
        self.verified()
        session = self.client.session
        session[SESSION_KEY]["verified_at"] = time.time() - 601
        session.save()

        self.assertEqual(self.reset().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_weak_password_is_rejected_and_can_be_retried(self):
        """A rejected password does not spend the verification."""
        self.verified()
        response = self.reset("short")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("new_password", response.json())

        self.assertEqual(self.reset().status_code, status.HTTP_204_NO_CONTENT)

    def test_existing_sessions_are_signed_out(self):
        """A session held before the reset stops authenticating after it."""
        elsewhere = APIClient()
        self.login(PASSWORD, client=elsewhere)

        self.verified()
        self.reset()

        request = HttpRequest()
        request.session = elsewhere.session
        self.assertFalse(get_user(request).is_authenticated)

    def test_unknown_and_incomplete_accounts_look_like_a_wrong_code(self):
        """The verify step reveals nothing about which numbers hold an account."""
        unknown = "+919000000000"
        unknown_response = self.verify(
            self.request_code(mobile_number=unknown, purpose=Purpose.PASSWORD_RESET),
            mobile_number=unknown,
        )

        self.user.registration_status = RegistrationStatus.PENDING_PROFILE
        self.user.save()
        incomplete_response = self.verify(self.request_code(purpose=Purpose.PASSWORD_RESET))

        for response in (unknown_response, incomplete_response):
            self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
            self.assertEqual(response.json()["detail"], "Invalid or expired code.")
