"""Messaging models for templates and delivery logs."""

import re

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseActivatableModel, BaseModel


class MessageTemplate(BaseModel, BaseActivatableModel):
    """Templated content for outbound messages."""

    class MessageType(models.TextChoices):
        """Supported message channels."""

        EMAIL = "email", "Email"
        SMS = "sms", "SMS"
        PUSH = "push", "Push"

    class Category(models.TextChoices):
        """Message category used by backends for routing/handling."""

        OTP = "OTP", "OTP"
        NOTIFICATION = "NOTIFICATION", "Notification"
        TRANSACTION = "TRANSACTION", "Transaction"

    class Priority(models.TextChoices):
        """Delivery priority levels."""

        HIGH = "HIGH", "High"
        MEDIUM = "MEDIUM", "Medium"
        LOW = "LOW", "Low"

    message_key = models.CharField(max_length=255)
    message_type = models.CharField(max_length=50, choices=MessageType.choices)
    subject = models.CharField(max_length=512, blank=True)
    content = models.TextField()
    data_schema = models.JSONField(default=dict, blank=True)
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    category = models.CharField(
        max_length=20,
        choices=Category.choices,
        default=Category.NOTIFICATION,
    )
    max_retries = models.PositiveSmallIntegerField(default=0)
    provider_template_id = models.CharField(max_length=255, blank=True)

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["message_key", "message_type"],
                name="unique_message_key_type",
            ),
            models.CheckConstraint(
                check=models.Q(message_key__regex=r"^[A-Z][A-Z0-9_]*$"),
                name="messagetemplate_message_key_upper_snake",
            ),
        ]

    def clean(self):
        """Validate template configuration."""

        super().clean()
        if not re.match(r"^[A-Z][A-Z0-9_]*$", self.message_key):
            raise ValidationError(
                {
                    "message_key": (
                        "Must be UPPERCASE_SNAKE_CASE using letters, numbers, and "
                        "underscores (e.g. CASE_FILING_SUBMITTED)."
                    )
                }
            )
        if self.message_type == self.MessageType.EMAIL.value and not self.subject:
            raise ValidationError({"subject": "Subject is required for email templates."})
        self._validate_data_schema()

    def _validate_data_schema(self):
        """Ensure data_schema is a valid JSON Schema document."""

        if not isinstance(self.data_schema, dict):
            raise ValidationError({"data_schema": "Must be a JSON object."})
        if not self.data_schema:
            return
        try:
            from jsonschema import validators
        except ImportError:
            # The project declares jsonschema; skip only when it is absent.
            return
        try:
            validator_cls = validators.validator_for(self.data_schema)
            validator_cls.check_schema(self.data_schema)
        except Exception as exc:
            raise ValidationError({"data_schema": str(exc)}) from exc

    def __str__(self):
        return f"{self.message_key} ({self.message_type})"


class MessageLog(BaseModel):
    """Persistent record of a message dispatch attempt."""

    class Status(models.TextChoices):
        """Delivery statuses."""

        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"
        FILTERED = "filtered", "Filtered"

    template = models.ForeignKey(
        MessageTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="logs",
    )
    message_type = models.CharField(
        max_length=50,
        choices=MessageTemplate.MessageType.choices,
    )
    message_key = models.CharField(max_length=255)
    recipient = models.JSONField()
    context = models.JSONField(default=dict)
    rendered_subject = models.CharField(max_length=512, blank=True)
    rendered_content = models.TextField(blank=True)
    status = models.CharField(
        max_length=50,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    max_retries = models.PositiveSmallIntegerField(default=0)
    provider_message_id = models.CharField(max_length=255, blank=True)
    correlation_id = models.CharField(max_length=255, blank=True, db_index=True)
    provider = models.CharField(max_length=50, blank=True)
    error_message = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    # Provider-specific delivery details (e.g. failure_code, gateway_status).
    provider_metadata = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.CheckConstraint(
                check=models.Q(message_key__regex=r"^[A-Z][A-Z0-9_]*$"),
                name="messagelog_message_key_upper_snake",
            ),
        ]

    def can_retry(self):
        """Return True when the message may be attempted again."""

        terminal = (self.Status.SENT.value, self.Status.FILTERED.value)
        return self.status not in terminal and self.attempt_count <= self.max_retries

    def __str__(self):
        return f"{self.message_key} ({self.status})"
