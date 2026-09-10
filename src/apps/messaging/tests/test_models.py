"""Tests for messaging models."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.messaging.models import MessageLog, MessageTemplate


class MessageTemplateTests(TestCase):
    """MessageTemplate model tests."""

    def setUp(self):
        self.template_data = {
            "message_key": "case_filing_submitted",
            "message_type": MessageTemplate.MessageType.EMAIL.value,
            "subject": "Case {{ case_number }} filed",
            "content": "Your case {{ case_number }} was filed.",
            "data_schema": {
                "type": "object",
                "required": ["case_number"],
                "properties": {
                    "case_number": {"type": "string"},
                },
            },
        }

    def create_template(self, **overrides):
        data = {**self.template_data, **overrides}
        return MessageTemplate.objects.create(**data)

    def build_template(self, **overrides):
        data = {**self.template_data, **overrides}
        return MessageTemplate(**data)

    def test_create_template(self):
        template = self.create_template()
        self.assertEqual(template.message_key, "case_filing_submitted")
        self.assertEqual(template.priority, MessageTemplate.Priority.MEDIUM.value)
        self.assertTrue(template.is_active)

    def test_message_key_must_be_snake_case(self):
        with self.assertRaises(ValidationError):
            self.build_template(message_key="Invalid-Key").full_clean()
        with self.assertRaises(ValidationError):
            self.build_template(message_key="123_invalid").full_clean()

    def test_email_requires_subject(self):
        with self.assertRaises(ValidationError):
            self.build_template(subject="").full_clean()

    def test_sms_template_allows_blank_subject(self):
        template = self.create_template(
            message_type=MessageTemplate.MessageType.SMS.value,
            subject="",
        )
        self.assertEqual(template.subject, "")

    def test_invalid_json_schema_rejected(self):
        with self.assertRaises(ValidationError):
            self.build_template(
                data_schema={"type": "not_a_real_type"}
            ).full_clean()

    def test_unique_key_and_type(self):
        self.create_template()
        with self.assertRaises(IntegrityError):
            self.create_template()

    def test_string_representation(self):
        template = self.create_template()
        self.assertIn("case_filing_submitted", str(template))


class MessageLogTests(TestCase):
    """MessageLog model tests."""

    def setUp(self):
        self.template = MessageTemplate.objects.create(
            message_key="case_filing_submitted",
            message_type=MessageTemplate.MessageType.EMAIL.value,
            subject="Case filed",
            content="Your case was filed.",
        )

    def create_log(self, **overrides):
        data = {
            "template": self.template,
            "message_type": MessageTemplate.MessageType.EMAIL.value,
            "message_key": "case_filing_submitted",
            "recipient": {"email": "user@example.com"},
            "context": {"case_number": "CASE-1"},
            "max_retry": 2,
        }
        data.update(overrides)
        return MessageLog.objects.create(**data)

    def test_can_retry_when_under_limit(self):
        log = self.create_log(attempt_count=1)
        self.assertTrue(log.can_retry())

    def test_can_retry_at_limit(self):
        log = self.create_log(attempt_count=2)
        self.assertTrue(log.can_retry())

    def test_cannot_retry_over_limit(self):
        log = self.create_log(attempt_count=3)
        self.assertFalse(log.can_retry())

    def test_cannot_retry_when_sent(self):
        log = self.create_log(
            attempt_count=1,
            status=MessageLog.Status.SENT.value,
        )
        self.assertFalse(log.can_retry())
