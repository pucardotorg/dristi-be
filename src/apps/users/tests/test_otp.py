"""OTP issue, consumption and delivery (spec 0005 sections 4.1.3 and 5.1)."""

from unittest.mock import patch

from apps.messaging.models import MessageLog, MessageTemplate
from apps.users.services.otp import (
    MESSAGE_KEYS,
    Purpose,
    issue_otp,
    verify_and_consume_otp,
)

from .base import MOBILE, OTPTestCase


class OTPConsumptionTests(OTPTestCase):
    """The code is single-use."""

    def test_code_cannot_be_replayed(self):
        """A verified code is destroyed, so the second attempt fails."""
        with patch("apps.users.services.otp._send_sms") as send:
            issue_otp(MOBILE, Purpose.REGISTER)
        code = send.call_args[0][1]

        self.assertTrue(verify_and_consume_otp(MOBILE, code, Purpose.REGISTER))
        self.assertFalse(verify_and_consume_otp(MOBILE, code, Purpose.REGISTER))

    def test_purposes_do_not_share_codes(self):
        """A register code does not authorise a login."""
        with patch("apps.users.services.otp._send_sms") as send:
            issue_otp(MOBILE, Purpose.REGISTER)
        code = send.call_args[0][1]

        self.assertFalse(verify_and_consume_otp(MOBILE, code, Purpose.LOGIN))


class OTPDeliveryTests(OTPTestCase):
    """Delivery goes through the messaging app, not a local stub.

    These are the only OTP tests that do not patch _send_sms, so they are what
    catches a missing or renamed message template.
    """

    def test_register_code_is_queued_with_the_registration_template(self):
        """A register-purpose code queues an SMS against its own template."""
        issue_otp(MOBILE, Purpose.REGISTER)

        log = MessageLog.objects.get()
        self.assertEqual(log.message_key, "ACCOUNT_REGISTRATION_OTP_SMS")
        self.assertEqual(log.message_type, "sms")
        self.assertEqual(log.recipient, {"phone_number": MOBILE})
        self.assertEqual(log.status, MessageLog.Status.PENDING.value)

    def test_login_code_is_queued_with_the_login_template(self):
        """A login-purpose code uses the template the messaging app ships."""
        issue_otp(MOBILE, Purpose.LOGIN)

        self.assertEqual(MessageLog.objects.get().message_key, "ACCOUNT_LOGIN_OTP_SMS")

    def test_the_code_reaches_the_message_context(self):
        """The context carries the code the cache will verify against."""
        issue_otp(MOBILE, Purpose.REGISTER)

        code = MessageLog.objects.get().context["otp"]
        self.assertTrue(verify_and_consume_otp(MOBILE, code, Purpose.REGISTER))

    def test_every_purpose_has_a_template(self):
        """No purpose can be added without a template to send it with."""
        for purpose in Purpose.CHOICES:
            self.assertIn(purpose, MESSAGE_KEYS)
            self.assertTrue(
                MessageTemplate.objects.filter(
                    message_key=MESSAGE_KEYS[purpose], message_type="sms"
                ).exists(),
                f"No SMS template seeded for purpose {purpose!r}.",
            )
