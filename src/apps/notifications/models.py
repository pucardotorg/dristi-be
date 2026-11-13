"""In-app notification inbox model (spec 0031 §1)."""

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel


class Notification(BaseModel):
    """One item in one user's in-app notification inbox.

    High-volume operational data: inherits :class:`BaseModel` (UUID id,
    timestamps, audit users) but deliberately not ``BaseAuditableModel`` — a
    per-row history table is not needed. Notifications are created only through
    ``apps.notifications.services.notify``; clients may read them and change
    their read state, never create or edit them.
    """

    class Priority(models.TextChoices):
        """Presentation hint; does not reorder the stream."""

        HIGH = "HIGH", "High"
        NORMAL = "NORMAL", "Normal"
        LOW = "LOW", "Low"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    event_type = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=256)
    body = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)
    priority = models.CharField(
        max_length=16,
        choices=Priority.choices,
        default=Priority.NORMAL,
        db_index=True,
    )
    read_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(event_type__regex=r"^[A-Z][A-Z0-9_]*$"),
                name="notif_event_type_upper_snake",
            ),
        ]
        indexes = [
            models.Index(
                fields=["recipient", "read_at"],
                name="notif_recipient_read_idx",
            ),
            models.Index(
                fields=["recipient", "-created_at"],
                name="notif_recipient_created_idx",
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.event_type} -> {self.recipient_id}"

    @property
    def is_read(self) -> bool:
        """Whether the recipient has read this notification."""
        return self.read_at is not None
