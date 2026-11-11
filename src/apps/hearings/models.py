"""Hearings models (spec 0023 #2)."""

import datetime
from functools import reduce
from operator import or_

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.models import CODE_RE, BaseActivatableModel, BaseAuditableModel, BaseModel

from .enums import (
    BOARD_STATUSES,
    OFF_BOARD_STATUS_ORDER,
    STATUS_ORDER,
    UNSEQUENCED_STATUSES,
    CalendarEntryType,
    CancellationReason,
    HearingMode,
    HearingStatus,
    ReleaseReason,
    Side,
)

# Messages shared by the model rules and the database constraints behind them.
CAPACITY_REQUIRED_MESSAGE = "Enter a capacity of at least 1 for a reduced sitting."
CAPACITY_NOT_ALLOWED_MESSAGE = (
    "Capacity can be set only for a reduced sitting; leave it empty for other entry types."
)
CONFIRMED_REQUIRED_MESSAGE = "Required once the hearing is confirmed."
CONFIRMED_NOT_ALLOWED_MESSAGE = (
    "Leave empty until the hearing is confirmed; a provisional or released date has none."
)
STARTED_REQUIRED_MESSAGE = "Required once the hearing has been started."
IN_PROGRESS_REQUIRED_MESSAGE = "Required while the hearing is in progress."
COMPLETED_REQUIRED_MESSAGE = "Required when the hearing is completed."
COMPLETED_ONLY_MESSAGE = "Set only when the hearing is completed."
ABANDONED_REQUIRED_MESSAGE = "Required when the hearing is abandoned."
CANCELLED_REQUIRED_MESSAGE = "Required when the hearing is cancelled."
CANCELLED_ONLY_MESSAGE = "Set only when the hearing is cancelled."
RELEASED_REQUIRED_MESSAGE = "Required when the hearing is released."
RELEASED_ONLY_MESSAGE = "Set only when the hearing is released."
HELD_MOVE_ONLY_MESSAGE = "Set only on a date held by a rescheduling order."
OWN_PREVIOUS_HEARING_MESSAGE = "A hearing cannot be its own previous hearing."
MOVES_ITSELF_MESSAGE = "A hearing cannot hold a move of itself."
SAME_CASE_HEARING_MESSAGE = "Must be a hearing of the same case."
CASE_COURT_MESSAGE = "Must be the court the case is listed in."
CASE_HAS_NO_COURT_MESSAGE = "This case has no court yet, so it cannot be listed."
NEGATIVE_DURATION_MESSAGE = "Cannot be negative."
LAST_START_BEFORE_FIRST_MESSAGE = "Cannot be earlier than the first start."
ONE_SCHEDULED_PER_CASE_MESSAGE = "This case already has a scheduled hearing."
ONE_IN_PROGRESS_PER_CASE_MESSAGE = "This case already has a hearing in progress."
BOARD_SEQUENCE_TAKEN_MESSAGE = (
    "Another hearing on this court's board for this date already has this serial number."
)
ONE_HOLD_PER_ORDER_MESSAGE = "This order already holds a provisional date."
SEQUENCE_IFF_ON_BOARD_MESSAGE = (
    "A provisional or released hearing has no serial number; "
    "every other hearing needs a serial number of at least 1."
)
HOLD_HAS_ORDER_MESSAGE = "A provisional hearing must have the draft order that holds it."
STARTED_BEFORE_ENDED_MESSAGE = (
    "An ended hearing needs a start time, and cannot end before it started."
)
STATUS_ORDER_MESSAGE = "The status order does not match the status."


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


CONFIRMED_STATUSES = tuple(status for status in HearingStatus if status not in UNSEQUENCED_STATUSES)

# Fields whose presence follows the status (#3, #6, #7). Each rule is
# ``(field, statuses it is required in, message when missing,
# statuses it is allowed in, message when set elsewhere)``. ``None`` allows it
# in every status: a field that records history (a first start, an
# abandonment) is kept when the hearing later moves on.
STATUS_FIELD_RULES = (
    (
        "confirmed_at",
        CONFIRMED_STATUSES,
        CONFIRMED_REQUIRED_MESSAGE,
        CONFIRMED_STATUSES,
        CONFIRMED_NOT_ALLOWED_MESSAGE,
    ),
    (
        "started_at",
        (HearingStatus.IN_PROGRESS, HearingStatus.COMPLETED),
        STARTED_REQUIRED_MESSAGE,
        None,
        None,
    ),
    ("last_started_at", (HearingStatus.IN_PROGRESS,), IN_PROGRESS_REQUIRED_MESSAGE, None, None),
    (
        "ended_at",
        (HearingStatus.COMPLETED,),
        COMPLETED_REQUIRED_MESSAGE,
        (HearingStatus.COMPLETED,),
        COMPLETED_ONLY_MESSAGE,
    ),
    ("adjournment_sought_by", (), None, (HearingStatus.COMPLETED,), COMPLETED_ONLY_MESSAGE),
    ("abandoned_at", (HearingStatus.ABANDONED,), ABANDONED_REQUIRED_MESSAGE, None, None),
    (
        "cancelled_at",
        (HearingStatus.CANCELLED,),
        CANCELLED_REQUIRED_MESSAGE,
        (HearingStatus.CANCELLED,),
        CANCELLED_ONLY_MESSAGE,
    ),
    (
        "cancellation_reason",
        (HearingStatus.CANCELLED,),
        CANCELLED_REQUIRED_MESSAGE,
        (HearingStatus.CANCELLED,),
        CANCELLED_ONLY_MESSAGE,
    ),
    (
        "release_reason",
        (HearingStatus.RELEASED,),
        RELEASED_REQUIRED_MESSAGE,
        (HearingStatus.RELEASED,),
        RELEASED_ONLY_MESSAGE,
    ),
    (
        "moves_hearing",
        (),
        None,
        (HearingStatus.PROVISIONAL, HearingStatus.RELEASED),
        HELD_MOVE_ONLY_MESSAGE,
    ),
)


class Hearing(BaseModel, BaseAuditableModel):
    """One listing of a case before its court on a date (spec 0023 #2.1).

    Moved in place, never re-created, so its id stays valid for the processes
    and applications that point at it (#8). Rows are never deleted: every end
    is a status, and the history table times each transition (``HRG-08``).

    Write only through ``apps.hearings.services``, which take the court lock
    and check the transition table (#3, #11.5). ``status_order`` is derived
    from ``status`` on save.
    """

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="hearings")
    court = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="hearings",
        help_text="The case's court when the date was fixed.",
    )
    purpose = models.ForeignKey(HearingPurpose, on_delete=models.PROTECT, related_name="hearings")
    hearing_date = models.DateField(help_text="The court date, in IST.")
    sequence = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Serial number on the day's board. Empty while provisional or released.",
    )
    status = models.CharField(max_length=16, choices=HearingStatus.choices)
    status_order = models.PositiveSmallIntegerField(
        help_text="Derived from the status; the board sorts by it, then by serial number."
    )
    mode = models.CharField(
        max_length=16, choices=HearingMode.choices, default=HearingMode.IN_PERSON
    )
    original_date = models.DateField(
        help_text="The date first fixed; a reschedule never changes it."
    )
    reschedule_count = models.PositiveSmallIntegerField(default=0)
    previous_hearing = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="next_hearings",
        help_text="The hearing whose order fixed this date.",
    )
    source_order_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="The order that fixed or holds this date.",
    )
    moves_hearing = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="held_moves",
        help_text="On a provisional date held by a rescheduling order: the hearing it will move.",
    )
    order_id = models.UUIDField(
        null=True, blank=True, unique=True, help_text="The order passed in this hearing."
    )
    started_at = models.DateTimeField(null=True, blank=True, help_text="The first start.")
    ended_at = models.DateTimeField(null=True, blank=True)
    last_started_at = models.DateTimeField(
        null=True, blank=True, help_text="Start of the current in-progress period."
    )
    heard_duration = models.DurationField(
        default=datetime.timedelta,
        help_text="Total time the hearing was in progress, over every period.",
    )
    abandoned_at = models.DateTimeField(null=True, blank=True)
    adjournment_sought_by = models.CharField(
        max_length=16,
        choices=Side.choices,
        blank=True,
        help_text="On end: who sought the adjournment. Empty when business was done.",
    )
    attendance_locked_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(
        null=True, blank=True, help_text="When it became scheduled."
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(
        max_length=32, choices=CancellationReason.choices, blank=True
    )
    release_reason = models.CharField(max_length=32, choices=ReleaseReason.choices, blank=True)

    class Meta:
        """Meta options."""

        ordering = ("hearing_date", "status_order", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=["case"],
                condition=Q(status=HearingStatus.SCHEDULED),
                name="hearings_one_scheduled_per_case",
                violation_error_message=ONE_SCHEDULED_PER_CASE_MESSAGE,
            ),
            models.UniqueConstraint(
                fields=["case"],
                condition=Q(status=HearingStatus.IN_PROGRESS),
                name="hearings_one_in_progress_per_case",
                violation_error_message=ONE_IN_PROGRESS_PER_CASE_MESSAGE,
            ),
            models.UniqueConstraint(
                fields=["court", "hearing_date", "sequence"],
                condition=Q(status__in=BOARD_STATUSES),
                name="hearings_board_sequence",
                violation_error_message=BOARD_SEQUENCE_TAKEN_MESSAGE,
            ),
            models.UniqueConstraint(
                fields=["source_order_id"],
                condition=Q(status=HearingStatus.PROVISIONAL),
                name="hearings_one_hold_per_order",
                violation_error_message=ONE_HOLD_PER_ORDER_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(status__in=UNSEQUENCED_STATUSES, sequence__isnull=True)
                | (
                    ~Q(status__in=UNSEQUENCED_STATUSES) & Q(sequence__isnull=False, sequence__gte=1)
                ),
                name="hearings_sequence_iff_on_board",
                violation_error_message=SEQUENCE_IFF_ON_BOARD_MESSAGE,
            ),
            models.CheckConstraint(
                check=~Q(status=HearingStatus.PROVISIONAL) | Q(source_order_id__isnull=False),
                name="hearings_hold_has_order",
                violation_error_message=HOLD_HAS_ORDER_MESSAGE,
            ),
            # ``started_at__isnull=False`` closes a gap in the spec's
            # ``ended_at IS NULL OR started_at <= ended_at``: with no start,
            # ``NULL <= ended_at`` is NULL, and a CHECK that evaluates to NULL passes.
            models.CheckConstraint(
                check=Q(ended_at__isnull=True)
                | Q(started_at__isnull=False, started_at__lte=F("ended_at")),
                name="hearings_started_before_ended",
                violation_error_message=STARTED_BEFORE_ENDED_MESSAGE,
            ),
            # Keeps the board order right when a status is written with
            # ``update()``, which skips ``save()``.
            models.CheckConstraint(
                check=reduce(
                    or_,
                    (
                        Q(status=status, status_order=order)
                        for status, order in STATUS_ORDER.items()
                    ),
                ),
                name="hearings_status_order_matches_status",
                violation_error_message=STATUS_ORDER_MESSAGE,
            ),
        ]
        indexes = [
            models.Index(
                fields=["court", "hearing_date", "status_order", "sequence"],
                name="hearings_board_idx",
            ),
            models.Index(fields=["case", "hearing_date"], name="hearings_case_date_idx"),
            models.Index(fields=["court", "hearing_date", "status"], name="hearings_day_load_idx"),
            models.Index(fields=["status", "hearing_date"], name="hearings_sweep_idx"),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.case} on {self.hearing_date} ({self.get_status_display()})"

    def clean(self):
        """Apply the rules between fields that the database constraints do not cover."""
        super().clean()
        errors = {}
        for field, required_in, required_message, allowed_in, only_message in STATUS_FIELD_RULES:
            value = getattr(self, f"{field}_id" if field == "moves_hearing" else field)
            if value in (None, "") and self.status in required_in:
                errors.setdefault(field, []).append(required_message)
            elif (
                value not in (None, "") and allowed_in is not None and self.status not in allowed_in
            ):
                errors.setdefault(field, []).append(only_message)

        if self.heard_duration is not None and self.heard_duration < datetime.timedelta(0):
            errors.setdefault("heard_duration", []).append(NEGATIVE_DURATION_MESSAGE)
        if self.started_at and self.last_started_at and self.last_started_at < self.started_at:
            errors.setdefault("last_started_at", []).append(LAST_START_BEFORE_FIRST_MESSAGE)

        if self.previous_hearing_id:
            if self.previous_hearing_id == self.pk:
                errors.setdefault("previous_hearing", []).append(OWN_PREVIOUS_HEARING_MESSAGE)
            elif self.previous_hearing.case_id != self.case_id:
                errors.setdefault("previous_hearing", []).append(SAME_CASE_HEARING_MESSAGE)
        if self.moves_hearing_id and "moves_hearing" not in errors:
            if self.moves_hearing_id == self.pk:
                errors.setdefault("moves_hearing", []).append(MOVES_ITSELF_MESSAGE)
            elif self.moves_hearing.case_id != self.case_id:
                errors.setdefault("moves_hearing", []).append(SAME_CASE_HEARING_MESSAGE)

        # Only when the date is first fixed: a case transferred later keeps its
        # past hearings in the court that heard them.
        if self._state.adding and self.case_id and self.court_id:
            case_court_id = self.case.court_id
            if case_court_id is None:
                errors.setdefault("case", []).append(CASE_HAS_NO_COURT_MESSAGE)
            elif case_court_id != self.court_id:
                errors.setdefault("court", []).append(CASE_COURT_MESSAGE)

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Derive the status order and the first date, then validate before saving."""
        self.status_order = STATUS_ORDER.get(self.status, OFF_BOARD_STATUS_ORDER)
        # Nothing is fixed while the date sits in a draft (#7.2), so the first
        # fixed date follows it until the order is triggered.
        if self.status == HearingStatus.PROVISIONAL or self.original_date is None:
            self.original_date = self.hearing_date
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
