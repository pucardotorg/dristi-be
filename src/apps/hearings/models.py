"""Hearings models (spec 0023 #2)."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import CODE_RE, BaseActivatableModel, BaseAuditableModel, BaseModel

from .enums import CalendarEntryType

# Messages shared by the model rules and the database constraints behind them.
CAPACITY_REQUIRED_MESSAGE = "Enter a capacity of at least 1 for a reduced sitting."
CAPACITY_NOT_ALLOWED_MESSAGE = (
    "Capacity can be set only for a reduced sitting; leave it empty for other entry types."
)


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


class CourtCalendarEntry(BaseModel, BaseAuditableModel):
    """A day a court does not sit, or sits with a different capacity (spec 0023 #2.5).

    At most one entry per court and date. ``REDUCED_SITTING`` is a sitting day
    whose capacity is ``capacity_override``; every other type makes the date a
    non-sitting day (#4).
    """

    court = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="calendar_entries",
    )
    date = models.DateField()
    entry_type = models.CharField(max_length=32, choices=CalendarEntryType.choices)
    reason = models.CharField(max_length=255, help_text='Shown in the date picker, e.g. "Onam".')
    capacity_override = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Hearings the court can take that day. Only for a reduced sitting.",
    )

    class Meta:
        """Meta options."""

        ordering = ("date", "court")
        verbose_name = "Court calendar entry"
        verbose_name_plural = "Court calendar entries"
        constraints = [
            models.UniqueConstraint(
                fields=["court", "date"],
                name="hearings_calendar_entry_unique_court_date",
            ),
            models.CheckConstraint(
                check=Q(entry_type__in=CalendarEntryType.values),
                name="hearings_calendar_entry_type_valid",
            ),
            # ``isnull=False`` is needed: in SQL ``NULL >= 1`` is NULL, and a
            # CHECK that evaluates to NULL passes.
            models.CheckConstraint(
                check=~Q(entry_type=CalendarEntryType.REDUCED_SITTING)
                | Q(capacity_override__isnull=False, capacity_override__gte=1),
                name="hearings_calendar_entry_capacity_required",
                violation_error_message=CAPACITY_REQUIRED_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(entry_type=CalendarEntryType.REDUCED_SITTING)
                | Q(capacity_override__isnull=True),
                name="hearings_calendar_entry_capacity_only_reduced",
                violation_error_message=CAPACITY_NOT_ALLOWED_MESSAGE,
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.date} {self.get_entry_type_display()} ({self.reason})"

    def clean(self):
        """Report a capacity that does not match the entry type on its field."""
        super().clean()
        if self.entry_type == CalendarEntryType.REDUCED_SITTING:
            if not self.capacity_override:
                raise ValidationError({"capacity_override": CAPACITY_REQUIRED_MESSAGE})
        elif self.capacity_override is not None:
            raise ValidationError({"capacity_override": CAPACITY_NOT_ALLOWED_MESSAGE})

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)
