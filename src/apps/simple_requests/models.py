"""Models for the generic request and approval workflow.

This module is deliberately domain-agnostic: it knows about request types,
requests, their documents and their approval trail, and nothing about what
any particular request *means*. Consuming apps own their own models and
apply their side effects from a registered post-approval hook (see
``apps.simple_requests.hooks``).
"""

from django.conf import settings
from django.db import models

from apps.core.models import BaseActivatableModel, BaseModel


def request_document_upload_to(instance, filename):
    """Return the storage path for an uploaded request document."""
    return f"request-documents/{instance.request_id}/{filename}"


class RequestType(BaseModel, BaseActivatableModel):
    """Configuration for a kind of request (schema, documents, approval steps)."""

    code = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    schema = models.JSONField(default=dict, blank=True)
    min_documents = models.PositiveIntegerField(default=0)

    class Meta:
        """Meta options."""

        ordering = ("code",)
        verbose_name = "Request Type"
        verbose_name_plural = "Request Types"

    def __str__(self):
        """Return the human-readable type code."""
        return self.code


class ApprovalStep(BaseModel):
    """Template rule describing who approves a given step of a request type."""

    request_type = models.ForeignKey(
        RequestType,
        on_delete=models.CASCADE,
        related_name="approval_steps",
    )
    order = models.PositiveIntegerField(default=0)
    approver_role = models.CharField(
        max_length=150,
        blank=True,
        help_text="Name of the auth group whose members can approve this step.",
    )
    approver_group = models.ForeignKey(
        "auth.Group",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approval_steps",
    )
    condition = models.JSONField(
        default=dict,
        blank=True,
        help_text="Declarative rule evaluated lazily against the request; empty means always.",
    )

    class Meta:
        """Meta options."""

        ordering = ("request_type", "order")
        unique_together = ("request_type", "order")
        verbose_name = "Approval Step"
        verbose_name_plural = "Approval Steps"

    def __str__(self):
        """Return a readable identifier for the step."""
        return f"{self.request_type.code} step {self.order}"


class Request(BaseModel):
    """A request raised by a user, routed through approval steps."""

    class Status(models.TextChoices):
        """Lifecycle states of a request."""

        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    OPEN_STATUSES = (Status.DRAFT, Status.PENDING)

    request_type = models.ForeignKey(
        RequestType,
        on_delete=models.PROTECT,
        related_name="requests",
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="requests",
    )
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    version = models.PositiveIntegerField(default=1)
    current_step = models.PositiveIntegerField(default=0)

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        verbose_name = "Request"
        verbose_name_plural = "Requests"

    def __str__(self):
        """Return a readable identifier for the request."""
        return f"{self.request_type_id and self.request_type.code} ({self.pk})"

    @property
    def current_approval(self):
        """Return the pending approval for the current round, if any."""
        return self.approvals.filter(
            version=self.version,
            status=RequestApproval.Status.PENDING,
        ).first()

    def is_open(self):
        """Return ``True`` when the request can still move through approval."""
        return self.status in self.OPEN_STATUSES


class RequestDocument(BaseModel):
    """A document attached to a request."""

    request = models.ForeignKey(
        Request,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    file = models.FileField(upload_to=request_document_upload_to)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_request_documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Meta options."""

        ordering = ("uploaded_at",)
        verbose_name = "Request Document"
        verbose_name_plural = "Request Documents"

    def __str__(self):
        """Return the stored file name."""
        return self.file.name or str(self.pk)

    @property
    def filename(self):
        """Return the base file name without the storage directory."""
        return (self.file.name or "").rsplit("/", 1)[-1]


class RequestApproval(BaseModel):
    """Per-request instance of an approval step: who was asked, what they decided."""

    class Status(models.TextChoices):
        """Decision states of an approval."""

        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        SKIPPED = "skipped", "Skipped"

    DECISIONS = (Status.APPROVED, Status.REJECTED)

    request = models.ForeignKey(
        Request,
        on_delete=models.CASCADE,
        related_name="approvals",
    )
    step = models.ForeignKey(
        ApprovalStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approvals",
    )
    step_order = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="request_approvals",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    comments = models.TextField(blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Meta options."""

        ordering = ("request", "version", "step_order")
        unique_together = ("request", "version", "step_order")
        verbose_name = "Request Approval"
        verbose_name_plural = "Request Approvals"

    def __str__(self):
        """Return a readable identifier for the approval."""
        return f"{self.request_id} v{self.version} step {self.step_order} ({self.status})"
