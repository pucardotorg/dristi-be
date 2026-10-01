"""The eSign transaction and its state machine (spec 0015 #5)."""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import BaseModel

from . import conf
from .constants import (
    RETRYABLE_STATUSES,
    TERMINAL_STATUSES,
    EntityType,
    ESignStatus,
)
from .exceptions import ESignInvalidTransition

HEX_HASH_PATTERN = re.compile(r"^[0-9a-f]+$")

# Placement keys the domain understands. The PDF Service owns the authoritative
# validation against the document; these are the shape checks that can be made
# without the bytes.
PLACEHOLDER_NUMERIC_KEYS = ("x", "y", "width", "height")


class ESignTransaction(BaseModel):
    """One signing attempt for one document with one ESP.

    A transaction is never mutated into a second attempt: `FAILURE`/`EXPIRED`
    are dead ends and a retry creates a new row linked by ``retry_of``, which
    keeps ``(provider, provider_transaction_id)`` unique and preserves the
    audit trail of every attempt.
    """

    Status = ESignStatus
    EntityType = EntityType

    organization_id = models.UUIDField(null=True, blank=True, db_index=True)
    module = models.CharField(max_length=64)
    entity_type = models.CharField(max_length=32, choices=EntityType.choices, blank=True)
    entity_id = models.CharField(max_length=64, blank=True, db_index=True)
    signer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="esign_transactions",
    )
    provider = models.CharField(max_length=32)
    provider_transaction_id = models.CharField(max_length=128, blank=True)
    source_file_id = models.CharField(max_length=64)
    placeholder_file_id = models.CharField(max_length=64, blank=True)
    signed_file_id = models.CharField(max_length=64, blank=True)
    sign_placeholder = models.JSONField(default=dict, blank=True)
    document_hash = models.CharField(max_length=128, blank=True)
    signature_field_name = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ESignStatus.choices,
        default=ESignStatus.PENDING.value,
    )
    attempt_count = models.PositiveSmallIntegerField(default=1)
    retry_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="retries",
    )
    request_audit = models.JSONField(default=dict, blank=True)
    response_audit = models.JSONField(default=dict, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.TextField(blank=True)
    expires_at = models.DateTimeField()
    callback_received_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Meta options."""

        ordering = ["-created_at"]
        verbose_name = "eSign Transaction"
        verbose_name_plural = "eSign Transactions"
        constraints = [
            # An ESP id is only unique within the ESP that issued it, so the
            # pair is the real identity. The condition excludes rows whose id
            # has not been assigned yet (a transaction that failed while its
            # request was being built), because "" is not an ESP id.
            models.UniqueConstraint(
                fields=["provider", "provider_transaction_id"],
                condition=~Q(provider_transaction_id=""),
                name="esign_unique_provider_transaction",
            ),
            models.CheckConstraint(
                check=~Q(status=ESignStatus.SUCCESS.value) | ~Q(signed_file_id=""),
                name="esign_success_requires_signed_file",
            ),
            # A row being signed must have a prepared document to sign. The
            # constraint stops at SIGNING rather than also covering SUCCESS,
            # because the placeholder cleanup of #9 deliberately deletes the
            # prepared document of terminal transactions and clears the id —
            # a completed transaction legitimately outlives its placeholder.
            models.CheckConstraint(
                check=~Q(status=ESignStatus.SIGNING.value) | ~Q(placeholder_file_id=""),
                name="esign_signing_requires_placeholder",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "expires_at"], name="esign_status_expires_idx"),
            models.Index(fields=["entity_type", "entity_id"], name="esign_entity_idx"),
            models.Index(fields=["organization_id", "created_at"], name="esign_org_created_idx"),
        ]

    def __str__(self):
        """Return a support-friendly identifier."""

        return f"{self.provider}:{self.provider_transaction_id or self.pk} ({self.status})"

    # -- invariants ---------------------------------------------------------
    def clean(self):
        """Validate the invariants that no database constraint can express."""

        super().clean()
        errors = {}

        if not isinstance(self.sign_placeholder, dict):
            errors["sign_placeholder"] = "Signature placement must be an object."
        else:
            for key in PLACEHOLDER_NUMERIC_KEYS:
                value = self.sign_placeholder.get(key)
                if value is None:
                    continue
                if isinstance(value, bool) or not isinstance(value, int | float):
                    errors["sign_placeholder"] = f"{key} must be a number."
                elif key in ("width", "height") and value <= 0:
                    errors["sign_placeholder"] = f"{key} must be greater than zero."
                elif value < 0:
                    errors["sign_placeholder"] = f"{key} must not be negative."
            page = self.sign_placeholder.get("page")
            if page is not None and (isinstance(page, bool) or not isinstance(page, int)):
                errors["sign_placeholder"] = "page must be an integer."

        if self.document_hash and not HEX_HASH_PATTERN.fullmatch(self.document_hash):
            errors["document_hash"] = "Document hash must be a lowercase hex digest."

        if self.status == ESignStatus.SUCCESS.value and not self.signed_file_id:
            errors["signed_file_id"] = "A successful transaction must carry a signed file id."

        if self.status == ESignStatus.SIGNING.value and not self.placeholder_file_id:
            errors["placeholder_file_id"] = "A prepared document is required to sign."

        if errors:
            raise ValidationError(errors)

    # -- derived state ------------------------------------------------------
    @property
    def is_terminal(self) -> bool:
        """Whether no further transition is possible."""

        return self.status in TERMINAL_STATUSES

    @property
    def is_retryable(self) -> bool:
        """Whether a new attempt may be created from this row."""

        return self.status in RETRYABLE_STATUSES

    def is_callback_window_open(self, now=None) -> bool:
        """Whether a callback may still be accepted (TTL plus grace)."""

        now = now or timezone.now()
        return now <= self.expires_at + conf.callback_grace_period()

    # -- transitions --------------------------------------------------------
    def mark_signing(self, *, save: bool = True):
        """Move ``PENDING`` to ``SIGNING`` — the concurrency guard of #8.2."""

        self._require(ESignStatus.PENDING.value)
        self.status = ESignStatus.SIGNING.value
        if self.callback_received_at is None:
            self.callback_received_at = timezone.now()
        if save:
            self.save(update_fields=["status", "callback_received_at", "updated_at"])
        return self

    def mark_success(self, *, signed_file_id: str, response_audit: dict | None = None):
        """Move ``SIGNING`` to ``SUCCESS`` with the stored signed document."""

        self._require(ESignStatus.SIGNING.value)
        if not signed_file_id:
            raise ESignInvalidTransition("A signed file id is required to complete a transaction.")
        self.status = ESignStatus.SUCCESS.value
        self.signed_file_id = signed_file_id
        self.completed_at = timezone.now()
        self.failure_code = ""
        self.failure_message = ""
        if response_audit is not None:
            self.response_audit = response_audit
        self.save(
            update_fields=[
                "status",
                "signed_file_id",
                "completed_at",
                "failure_code",
                "failure_message",
                "response_audit",
                "updated_at",
            ]
        )
        return self

    def mark_failed(self, code: str, message: str = "", response_audit: dict | None = None):
        """Record a failure, keeping the placeholder for a retry."""

        self._require(ESignStatus.PENDING.value, ESignStatus.SIGNING.value)
        self.status = ESignStatus.FAILURE.value
        self.failure_code = code
        self.failure_message = message
        if response_audit is not None:
            self.response_audit = response_audit
        self.save(
            update_fields=[
                "status",
                "failure_code",
                "failure_message",
                "response_audit",
                "updated_at",
            ]
        )
        return self

    def mark_expired(self, code: str = "", message: str = ""):
        """Record that no callback arrived within the TTL."""

        self._require(ESignStatus.PENDING.value)
        self.status = ESignStatus.EXPIRED.value
        self.failure_code = code
        self.failure_message = message
        self.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
        return self

    def _require(self, *allowed: str) -> None:
        """Raise unless the current status is one of ``allowed``."""

        if self.status not in allowed:
            raise ESignInvalidTransition(
                f"Cannot move a {self.status} transaction; expected one of {', '.join(allowed)}."
            )
