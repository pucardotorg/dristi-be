"""Standalone terms acceptance (spec 0005 section 6): POST /users/me/terms."""

from datetime import timedelta

from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from apps.users.models import RegistrationStatus, Role, User

from .base import MOBILE, OTPTestCase


class TermsAcceptanceTests(OTPTestCase):
    """An account created outside the wizard accepts the terms on its own."""

    def setUp(self):
        """Create an account as filing would: past the wizard, no terms accepted."""
        super().setUp()
        self.user = User.objects.create_user(
            mobile_number=MOBILE,
            name="Asha Menon",
            role=Role.LITIGANT,
            registration_status=RegistrationStatus.COMPLETE,
        )
        self.client.force_authenticate(user=self.user)

    def accept(self, **body):
        """POST an acceptance, defaulting to a valid one."""
        return self.client.post(
            reverse("user-terms"), {"terms_accepted": True, **body}, format="json"
        )

    def test_acceptance_is_recorded(self):
        """POST stamps the version in force and opens the platform."""
        response = self.accept()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertTrue(body["has_current_terms"])
        self.assertEqual(body["terms_version_accepted"], settings.CURRENT_TERMS_VERSION)
        self.assertIsNone(body["next"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.terms_version_accepted, settings.CURRENT_TERMS_VERSION)
        self.assertIsNotNone(self.user.terms_accepted_at)
        self.assertEqual(self.user.updated_by, self.user)

    def test_version_comes_from_the_server(self):
        """A client-sent version or timestamp is ignored."""
        with self.settings(CURRENT_TERMS_VERSION=7):
            self.accept(terms_version=999, terms_accepted_at="2000-01-01T00:00:00Z")

        self.user.refresh_from_db()
        self.assertEqual(self.user.terms_version_accepted, 7)
        self.assertGreater(self.user.terms_accepted_at, timezone.now() - timedelta(minutes=1))

    def test_acceptance_must_be_affirmative(self):
        """A missing or false acceptance is refused and nothing is recorded."""
        for body in ({}, {"terms_accepted": False}):
            with self.subTest(body=body):
                response = self.client.post(reverse("user-terms"), body, format="json")
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        self.user.refresh_from_db()
        self.assertIsNone(self.user.terms_version_accepted)
        self.assertIsNone(self.user.terms_accepted_at)

    def test_repeating_acceptance_keeps_the_original_moment(self):
        """Accepting again changes nothing, so the evidence is not overwritten."""
        self.accept()
        self.user.refresh_from_db()
        first = self.user.terms_accepted_at

        response = self.accept()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertEqual(self.user.terms_accepted_at, first)

    def test_revised_terms_are_accepted_afresh(self):
        """Once the version is bumped, accepting again records the new one."""
        self.accept()

        with self.settings(CURRENT_TERMS_VERSION=settings.CURRENT_TERMS_VERSION + 1):
            response = self.accept()
            self.assertTrue(response.json()["has_current_terms"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.terms_version_accepted, settings.CURRENT_TERMS_VERSION + 1)

    def test_anonymous_caller_is_refused(self):
        """The terms are accepted by a signed-in account, never by a mobile number."""
        self.client.force_authenticate(user=None)
        response = self.accept()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
