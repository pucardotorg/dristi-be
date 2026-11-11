"""Hearings models (spec 0023 #2)."""

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import CODE_RE, BaseActivatableModel, BaseAuditableModel, BaseModel


class HearingPurpose(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """What a hearing is listed for, e.g. Appearance or Arguments (spec 0023 #2.2).

    Reference table edited in admin. ``code`` is what other modules pass and
    store, and the case lifecycle keys its stage rules on it, so it is not
    renamed. A purpose is retired with ``is_active = False``, never deleted:
    it stays on existing hearings but cannot be chosen for a new date.
    """

    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=128, help_text="Shown on the board and in the order.")
    description = models.TextField(blank=True)
    sequence = models.PositiveSmallIntegerField(help_text="Display order in dropdowns.")

    class Meta:
        """Meta options."""

        ordering = ("sequence", "code")
        verbose_name = "Hearing purpose"
        verbose_name_plural = "Hearing purposes"

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.label} ({self.code})"

    def clean(self):
        """Validate the code format."""
        super().clean()
        if self.code and not CODE_RE.fullmatch(self.code):
            raise ValidationError(
                {"code": "Must be uppercase snake_case matching ^[A-Z0-9_]+$ (e.g. APPEARANCE)."}
            )

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)
