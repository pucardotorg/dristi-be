"""Shared fixtures for the users test suite."""

from unittest.mock import patch

from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.services.otp import Purpose

MOBILE = "+919876543210"
PASSWORD = "a-sufficiently-long-passphrase"


class OTPTestCase(APITestCase):
    """Base class that clears the cache and captures issued codes."""

    def setUp(self):
        """Start each test with an empty cache."""
        cache.clear()

    def request_code(self, mobile_number=MOBILE, purpose=Purpose.REGISTER):
        """Call the OTP endpoint and return the code that was 'sent'."""
        sent = {}

        def capture(number, code, purpose):
            sent["code"] = code

        with patch("apps.users.services.otp._send_sms", side_effect=capture):
            response = self.client.post(
                reverse("otp-request"),
                {"mobile_number": mobile_number, "purpose": purpose},
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        return sent["code"]

    def create_account(self, mobile_number=MOBILE):
        """Run the OTP + POST /users step and return the response."""
        code = self.request_code(mobile_number)
        return self.client.post(
            reverse("user-create"),
            {"mobile_number": mobile_number, "otp": code},
            format="json",
        )

    def assert_meta(self, payload):
        """Assert the envelope required by spec 0000 section 8 is present."""
        self.assertIn("meta", payload)
        meta = payload["meta"]
        self.assertIn("timestamp", meta)
        self.assertIn("app_version", meta)
        self.assertEqual(meta["spec_version"], "1.0")
