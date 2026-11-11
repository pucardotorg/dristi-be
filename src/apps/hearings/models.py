"""Hearings models (spec 0023 #2)."""

import datetime
import uuid
from functools import reduce
from operator import or_

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.cases.selectors import get_attendance_roll
from apps.core.models import CODE_RE, BaseActivatableModel, BaseAuditableModel, BaseModel

from .enums import (
    ATTENDANCE_STATUSES,
    BOARD_STATUSES,
    CONFIRMED_STATUSES,
    COURT_SIDE_REASONS,
    MOVABLE_STATUSES,
    OFF_BOARD_STATUS_ORDER,
    STATUS_ORDER,
    UNCONFIRMED_BULK_STATUSES,
    UNSEQUENCED_STATUSES,
    AppearanceMode,
    AttendanceMark,
    AttendeeType,
    BulkItemResult,
    BulkMode,
    BulkRescheduleStatus,
    CalendarEntryType,
    CancellationReason,
    ChangeSource,
    HearingMode,
    HearingStatus,
    ReleaseReason,
    RescheduleReason,
    Side,
)

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
APPEARANCE_MODE_REQUIRED_MESSAGE = "Choose in person or video for someone marked present."
APPEARANCE_MODE_NOT_ALLOWED_MESSAGE = (
    "Only for someone marked present; leave it empty for absent or not required."
)
ATTENDANCE_NOT_STARTED_MESSAGE = "Attendance can be marked only once the hearing has been started."
ATTENDANCE_LOCKED_MESSAGE = "Attendance is locked: the hearing's order has been triggered."
NOT_ON_ROLL_MESSAGE = (
    "Not on this case's attendance roll. Only its complainants, accused and PoA holders, "
    "and an advocate line under each complainant or accused with an advocate, can be marked."
)
OWN_PREVIOUS_HEARING_MESSAGE = "A hearing cannot be its own previous hearing."
NOTHING_MOVED_MESSAGE = "A change must move the date, the purpose, or both."
SOUGHT_BY_MESSAGE = (
    "A party application is sought by the complainant or the accused; "
    "every other reason by the court."
)
ORDER_ONLY_REASON_MESSAGE = (
    "A party application or a judicial direction moves a hearing only through an order."
)
SOURCE_REF_REQUIRED_MESSAGE = "Required for a change made by an order or a bulk move."
SOURCE_REF_NOT_ALLOWED_MESSAGE = "Leave empty for a change made by court staff."
NOT_MOVABLE_MESSAGE = "Only a scheduled, passed-over or abandoned hearing can be moved."
FROM_DATE_MESSAGE = "Must be the hearing's date before the move."
FROM_PURPOSE_MESSAGE = "Must be the hearing's purpose before the move."
APPEND_ONLY_MESSAGE = "A date change is a log entry: it is never edited or deleted."
BULK_MODE_DATES_MESSAGE = (
    "Moving to one date needs a target date only; "
    "moving to the next available days needs a schedule-after date only."
)
BULK_REASON_MESSAGE = "A bulk move takes a court-side reason only; other moves need an order."
BULK_CONFIRMATION_MESSAGE = (
    "Confirmed time and user are set exactly when the job has been confirmed."
)
BULK_ITEM_MOVES_MESSAGE = "The new date must differ from the hearing's date."
BULK_ITEM_ERROR_CODE_MESSAGE = (
    "A failed item records its API error code (e.g. E10006); other items record none."
)
BULK_CONFIRMED_AFTER_EXPIRY_MESSAGE = "A preview cannot be confirmed after it expires."
BULK_JOB_COMPLETED_MESSAGE = "A completed job has no failed or unprocessed items."
BULK_JOB_PARTIAL_MESSAGE = "A partially failed job needs a failed item and no unprocessed ones."
BULK_JOB_DELETE_MESSAGE = "A confirmed job is the record of the moves it made: it is never deleted."
BULK_ITEM_RESULT_BEFORE_RUN_MESSAGE = "An item gets a result only while its job is running."
BULK_ITEM_FINAL_MESSAGE = "This item is finished: its result cannot change."
BULK_ITEM_SNAPSHOT_MESSAGE = "Must be the hearing's last change time at preview."
BULK_ITEM_COURT_MESSAGE = "Must be a hearing of the job's court."
BULK_ITEM_TARGET_DATE_MESSAGE = "Must be the job's target date."
BULK_ITEM_AFTER_DATE_MESSAGE = "Must be after the job's schedule-after date."
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


def _raise_broken_rules(rules):
    """Raise a ``ValidationError`` listing every rule in ``rules`` that does not hold.

    ``rules`` are ``(field, rule holds, message when it does not)``. Every
    broken rule is reported, not just the first one per field.
    """
    errors = {}
    for field, holds, message in rules:
        if not holds:
            errors.setdefault(field, []).append(message)
    if errors:
        raise ValidationError(errors)


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
            # isnull=False: with no start, NULL <= ended_at is NULL, and a NULL CHECK passes.
            models.CheckConstraint(
                check=Q(ended_at__isnull=True)
                | Q(started_at__isnull=False, started_at__lte=F("ended_at")),
                name="hearings_started_before_ended",
                violation_error_message=STARTED_BEFORE_ENDED_MESSAGE,
            ),
            # save() derives status_order; this also catches update(), which skips save().
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
        """Apply the rules between fields that the database constraints do not cover.

        Fields that record history (a first start, an abandonment) are only
        required, never refused: they are kept when the hearing moves on.
        """
        super().clean()
        status = self.status
        confirmed = status in CONFIRMED_STATUSES
        completed = status == HearingStatus.COMPLETED
        cancelled = status == HearingStatus.CANCELLED
        released = status == HearingStatus.RELEASED
        held = status in (HearingStatus.PROVISIONAL, HearingStatus.RELEASED)
        started = self.started_at and self.last_started_at
        # Only on create: a case transferred later keeps its past hearings in their court.
        newly_listed = self._state.adding and self.case_id and self.court_id
        case_court_id = self.case.court_id if newly_listed else None
        _raise_broken_rules(
            [
                ("confirmed_at", not confirmed or self.confirmed_at, CONFIRMED_REQUIRED_MESSAGE),
                ("confirmed_at", confirmed or not self.confirmed_at, CONFIRMED_NOT_ALLOWED_MESSAGE),
                (
                    "started_at",
                    status not in (HearingStatus.IN_PROGRESS, HearingStatus.COMPLETED)
                    or self.started_at,
                    STARTED_REQUIRED_MESSAGE,
                ),
                (
                    "last_started_at",
                    status != HearingStatus.IN_PROGRESS or self.last_started_at,
                    IN_PROGRESS_REQUIRED_MESSAGE,
                ),
                (
                    "last_started_at",
                    not started or self.last_started_at >= self.started_at,
                    LAST_START_BEFORE_FIRST_MESSAGE,
                ),
                ("ended_at", not completed or self.ended_at, COMPLETED_REQUIRED_MESSAGE),
                ("ended_at", completed or not self.ended_at, COMPLETED_ONLY_MESSAGE),
                (
                    "heard_duration",
                    self.heard_duration is None or self.heard_duration >= datetime.timedelta(0),
                    NEGATIVE_DURATION_MESSAGE,
                ),
                (
                    "adjournment_sought_by",
                    completed or not self.adjournment_sought_by,
                    COMPLETED_ONLY_MESSAGE,
                ),
                (
                    "abandoned_at",
                    status != HearingStatus.ABANDONED or self.abandoned_at,
                    ABANDONED_REQUIRED_MESSAGE,
                ),
                ("cancelled_at", not cancelled or self.cancelled_at, CANCELLED_REQUIRED_MESSAGE),
                ("cancelled_at", cancelled or not self.cancelled_at, CANCELLED_ONLY_MESSAGE),
                (
                    "cancellation_reason",
                    not cancelled or self.cancellation_reason,
                    CANCELLED_REQUIRED_MESSAGE,
                ),
                (
                    "cancellation_reason",
                    cancelled or not self.cancellation_reason,
                    CANCELLED_ONLY_MESSAGE,
                ),
                ("release_reason", not released or self.release_reason, RELEASED_REQUIRED_MESSAGE),
                ("release_reason", released or not self.release_reason, RELEASED_ONLY_MESSAGE),
                ("moves_hearing", held or not self.moves_hearing_id, HELD_MOVE_ONLY_MESSAGE),
                (
                    "moves_hearing",
                    not self.moves_hearing_id or self.moves_hearing_id != self.pk,
                    MOVES_ITSELF_MESSAGE,
                ),
                (
                    "moves_hearing",
                    not self.moves_hearing_id
                    or self.moves_hearing_id == self.pk
                    or self.moves_hearing.case_id == self.case_id,
                    SAME_CASE_HEARING_MESSAGE,
                ),
                (
                    "previous_hearing",
                    not self.previous_hearing_id or self.previous_hearing_id != self.pk,
                    OWN_PREVIOUS_HEARING_MESSAGE,
                ),
                (
                    "previous_hearing",
                    not self.previous_hearing_id
                    or self.previous_hearing_id == self.pk
                    or self.previous_hearing.case_id == self.case_id,
                    SAME_CASE_HEARING_MESSAGE,
                ),
                ("case", not newly_listed or case_court_id is not None, CASE_HAS_NO_COURT_MESSAGE),
                (
                    "court",
                    not newly_listed or case_court_id in (None, self.court_id),
                    CASE_COURT_MESSAGE,
                ),
            ]
        )

    def save(self, *args, **kwargs):
        """Derive the status order and the first date, then validate before saving."""
        self.status_order = STATUS_ORDER.get(self.status, OFF_BOARD_STATUS_ORDER)
        # A draft date is not fixed yet (#7.2), so original_date follows it until confirm.
        if self.status == HearingStatus.PROVISIONAL or self.original_date is None:
            self.original_date = self.hearing_date
        self.full_clean()
        super().save(*args, **kwargs)


class HearingAttendanceQuerySet(models.QuerySet):
    """Refuses to delete marks once a hearing's attendance is locked."""

    def delete(self):
        """Delete the marks, unless any belongs to a locked hearing.

        A full replace of the roll deletes the old marks first (#6.5), so
        without this a replace after the order is triggered would erase them.
        """
        if self.filter(hearing__attendance_locked_at__isnull=False).exists():
            raise ValidationError({"hearing": ATTENDANCE_LOCKED_MESSAGE})
        return super().delete()


class HearingAttendance(BaseModel):
    """One marked line on a hearing's attendance roll (spec 0023 #2.3).

    The roll is every complainant, accused and PoA holder on the case, with one
    advocate line under each complainant and accused that has an advocate
    (``ATT-01``), read from ``apps.cases`` ``get_attendance_roll``. An unmarked
    person has no row; the roll is complete when every line has one (``ATT-04``).
    Written only through ``services.courtroom``, which replaces the whole roll
    and checks each line is on it (#6.5).
    """

    hearing = models.ForeignKey(Hearing, on_delete=models.CASCADE, related_name="attendance")
    attendee_type = models.CharField(max_length=32, choices=AttendeeType.choices)
    participant_id = models.UUIDField(
        help_text="The party on the roll; for an advocate line, the party it sits under."
    )
    mark = models.CharField(max_length=16, choices=AttendanceMark.choices)
    appearance_mode = models.CharField(
        max_length=16,
        choices=AppearanceMode.choices,
        blank=True,
        help_text="How a present person appeared. Only with Present.",
    )

    objects = HearingAttendanceQuerySet.as_manager()

    class Meta:
        """Meta options."""

        ordering = ("hearing", "attendee_type", "participant_id")
        verbose_name = "Hearing attendance"
        verbose_name_plural = "Hearing attendance"
        constraints = [
            models.UniqueConstraint(
                fields=["hearing", "attendee_type", "participant_id"],
                name="hearings_attendance_one_mark_per_line",
            ),
            models.CheckConstraint(
                check=Q(attendee_type__in=AttendeeType.values),
                name="hearings_attendance_type_valid",
            ),
            models.CheckConstraint(
                check=Q(mark__in=AttendanceMark.values),
                name="hearings_attendance_mark_valid",
            ),
            models.CheckConstraint(
                check=~Q(mark=AttendanceMark.PRESENT)
                | Q(appearance_mode__in=AppearanceMode.values),
                name="hearings_attendance_present_has_mode",
                violation_error_message=APPEARANCE_MODE_REQUIRED_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(mark=AttendanceMark.PRESENT) | Q(appearance_mode=""),
                name="hearings_attendance_mode_only_present",
                violation_error_message=APPEARANCE_MODE_NOT_ALLOWED_MESSAGE,
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return (
            f"{self.get_attendee_type_display()} {self.participant_id}: {self.get_mark_display()}"
        )

    def clean(self):
        """Report a mode that does not match the mark, and a hearing that cannot take attendance."""
        super().clean()
        errors = {}
        if self.mark == AttendanceMark.PRESENT and not self.appearance_mode:
            errors["appearance_mode"] = APPEARANCE_MODE_REQUIRED_MESSAGE
        elif self.mark != AttendanceMark.PRESENT and self.appearance_mode:
            errors["appearance_mode"] = APPEARANCE_MODE_NOT_ALLOWED_MESSAGE
        if self.hearing_id:
            hearing = self.hearing
            if hearing.attendance_locked_at:
                errors["hearing"] = ATTENDANCE_LOCKED_MESSAGE
            elif hearing.status not in ATTENDANCE_STATUSES or hearing.started_at is None:
                errors["hearing"] = ATTENDANCE_NOT_STARTED_MESSAGE
            if self.participant_id and self.attendee_type and not self._is_on_roll(hearing):
                errors["participant_id"] = NOT_ON_ROLL_MESSAGE
        if errors:
            raise ValidationError(errors)

    def _is_on_roll(self, hearing):
        """Whether this line is on the case's attendance roll (#6.5, ``E10011``).

        A malformed id counts as on the roll here: ``clean_fields`` already
        reports it, and one error per mistake is enough.
        """
        try:
            participant_id = uuid.UUID(str(self.participant_id))
        except ValueError:
            return True
        return any(
            entry.type == self.attendee_type and entry.participant_id == participant_id
            for entry in get_attendance_roll(hearing.case_id)
        )

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refuse to delete a mark once the hearing's attendance is locked."""
        if self.hearing.attendance_locked_at:
            raise ValidationError({"hearing": ATTENDANCE_LOCKED_MESSAGE})
        return super().delete(*args, **kwargs)


class HearingDateChangeQuerySet(models.QuerySet):
    """Refuses bulk edits and deletes: the log is append-only (#2.4)."""

    def bulk_create(self, objs, *args, **kwargs):
        """Validate each entry first, which ``bulk_create`` would skip."""
        objs = list(objs)
        for obj in objs:
            obj.full_clean()
        return super().bulk_create(objs, *args, **kwargs)

    def update(self, **kwargs):
        """Refuse: a date change is never edited."""
        raise ValidationError(APPEND_ONLY_MESSAGE)

    def delete(self):
        """Refuse: a date change is never deleted."""
        raise ValidationError(APPEND_ONLY_MESSAGE)


class HearingDateChange(BaseModel):
    """One move of a hearing that has not been heard (spec 0023 #2.4).

    Append-only: written in the same transaction as the move, before the
    hearing itself changes (#8.2), and never edited or deleted. It answers how
    many times, why and at whose request a case was adjourned, which the
    history table is not built to (#11.3). A change of a provisional date in a
    draft writes no row: nothing announced has moved (#7.2).
    """

    hearing = models.ForeignKey(Hearing, on_delete=models.PROTECT, related_name="date_changes")
    from_date = models.DateField()
    to_date = models.DateField()
    from_purpose = models.ForeignKey(HearingPurpose, on_delete=models.PROTECT, related_name="+")
    to_purpose = models.ForeignKey(
        HearingPurpose,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="The same as the purpose before when only the date moves.",
    )
    reason_code = models.CharField(max_length=32, choices=RescheduleReason.choices)
    reason_text = models.TextField(blank=True)
    sought_by = models.CharField(max_length=16, choices=Side.choices)
    source = models.CharField(max_length=16, choices=ChangeSource.choices)
    source_ref = models.UUIDField(
        null=True, blank=True, help_text="The order id or the bulk move job id."
    )

    objects = HearingDateChangeQuerySet.as_manager()

    class Meta:
        """Meta options."""

        ordering = ("hearing", "created_at")
        verbose_name = "Hearing date change"
        verbose_name_plural = "Hearing date changes"
        constraints = [
            models.CheckConstraint(
                check=~Q(from_date=F("to_date")) | ~Q(from_purpose=F("to_purpose")),
                name="hearings_date_change_moves_something",
                violation_error_message=NOTHING_MOVED_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(reason_code__in=RescheduleReason.values),
                name="hearings_date_change_reason_valid",
            ),
            models.CheckConstraint(
                check=Q(sought_by__in=Side.values),
                name="hearings_date_change_sought_by_valid",
            ),
            models.CheckConstraint(
                check=Q(
                    reason_code=RescheduleReason.PARTY_APPLICATION,
                    sought_by__in=(Side.COMPLAINANT, Side.ACCUSED),
                )
                | (~Q(reason_code=RescheduleReason.PARTY_APPLICATION) & Q(sought_by=Side.COURT)),
                name="hearings_date_change_sought_by_matches_reason",
                violation_error_message=SOUGHT_BY_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(source=ChangeSource.ORDER) | Q(reason_code__in=COURT_SIDE_REASONS),
                name="hearings_date_change_order_only_reasons",
                violation_error_message=ORDER_ONLY_REASON_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(source__in=ChangeSource.values),
                name="hearings_date_change_source_valid",
            ),
            models.CheckConstraint(
                check=Q(source=ChangeSource.COURT_ADMIN) | Q(source_ref__isnull=False),
                name="hearings_date_change_ref_required",
                violation_error_message=SOURCE_REF_REQUIRED_MESSAGE,
            ),
            models.CheckConstraint(
                check=~Q(source=ChangeSource.COURT_ADMIN) | Q(source_ref__isnull=True),
                name="hearings_date_change_ref_not_for_staff",
                violation_error_message=SOURCE_REF_NOT_ALLOWED_MESSAGE,
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.from_date} to {self.to_date}: {self.get_reason_code_display()}"

    def clean(self):
        """Check the hearing as it stands before the move (#8.2 writes this row first)."""
        super().clean()
        if not (self._state.adding and self.hearing_id):
            return
        hearing = self.hearing
        _raise_broken_rules(
            [
                ("hearing", hearing.status in MOVABLE_STATUSES, NOT_MOVABLE_MESSAGE),
                ("from_date", self.from_date == hearing.hearing_date, FROM_DATE_MESSAGE),
                ("from_purpose", self.from_purpose_id == hearing.purpose_id, FROM_PURPOSE_MESSAGE),
            ]
        )

    def save(self, *args, **kwargs):
        """Validate and write a new entry; an existing one is never edited."""
        if not self._state.adding:
            raise ValidationError(APPEND_ONLY_MESSAGE)
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refuse: a date change is never deleted."""
        raise ValidationError(APPEND_ONLY_MESSAGE)


class BulkRescheduleJobQuerySet(models.QuerySet):
    """Refuses to delete a confirmed job: its moves point at it."""

    def delete(self):
        """Delete only unconfirmed previews."""
        if self.exclude(status__in=UNCONFIRMED_BULK_STATUSES).exists():
            raise ValidationError(BULK_JOB_DELETE_MESSAGE)
        return super().delete()


class BulkRescheduleJob(BaseModel):
    """A court-side move of many hearings at once, previewed then run (spec 0023 #2.6, #8.3).

    Only court-side reasons are accepted: party and judicial reasons need an
    order. A preview stores the job and its items and changes nothing else;
    confirming queues ``tasks.run_bulk_reschedule``, which moves each item
    through the single-move service with ``source = BULK``.
    """

    court = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="bulk_reschedule_jobs",
    )
    mode = models.CharField(max_length=16, choices=BulkMode.choices)
    target_date = models.DateField(null=True, blank=True, help_text="Only when moving to one date.")
    schedule_after = models.DateField(
        null=True, blank=True, help_text="Only when moving to the next available days."
    )
    block_source_dates = models.BooleanField(
        default=False,
        help_text="After the moves, mark the dates moved away from as non-sitting.",
    )
    reason_code = models.CharField(max_length=32, choices=RescheduleReason.choices)
    reason_text = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=BulkRescheduleStatus.choices, default=BulkRescheduleStatus.PREVIEWED
    )
    preview_expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    objects = BulkRescheduleJobQuerySet.as_manager()

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        verbose_name = "Bulk reschedule job"
        verbose_name_plural = "Bulk reschedule jobs"
        constraints = [
            models.CheckConstraint(
                check=Q(
                    mode=BulkMode.TO_DATE, target_date__isnull=False, schedule_after__isnull=True
                )
                | Q(
                    mode=BulkMode.NEXT_AVAILABLE,
                    schedule_after__isnull=False,
                    target_date__isnull=True,
                ),
                name="hearings_bulk_job_mode_dates",
                violation_error_message=BULK_MODE_DATES_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(reason_code__in=COURT_SIDE_REASONS),
                name="hearings_bulk_job_court_side_reason",
                violation_error_message=BULK_REASON_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(status__in=BulkRescheduleStatus.values),
                name="hearings_bulk_job_status_valid",
            ),
            models.CheckConstraint(
                check=Q(
                    status__in=UNCONFIRMED_BULK_STATUSES,
                    confirmed_at__isnull=True,
                    confirmed_by__isnull=True,
                )
                | (
                    ~Q(status__in=UNCONFIRMED_BULK_STATUSES)
                    & Q(confirmed_at__isnull=False, confirmed_by__isnull=False)
                ),
                name="hearings_bulk_job_confirmation",
                violation_error_message=BULK_CONFIRMATION_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(confirmed_at__isnull=True) | Q(confirmed_at__lte=F("preview_expires_at")),
                name="hearings_bulk_job_confirmed_before_expiry",
                violation_error_message=BULK_CONFIRMED_AFTER_EXPIRY_MESSAGE,
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        when = self.target_date or f"after {self.schedule_after}"
        return f"{self.get_reason_code_display()} to {when} ({self.get_status_display()})"

    def clean(self):
        """Check a finished job's status against its items' results."""
        super().clean()
        if self._state.adding:
            return
        results = set(self.items.values_list("result", flat=True))
        unprocessed = BulkItemResult.PENDING in results
        failed = BulkItemResult.FAILED in results
        _raise_broken_rules(
            [
                (
                    "status",
                    self.status != BulkRescheduleStatus.COMPLETED or not (failed or unprocessed),
                    BULK_JOB_COMPLETED_MESSAGE,
                ),
                (
                    "status",
                    self.status != BulkRescheduleStatus.PARTIALLY_FAILED
                    or (failed and not unprocessed),
                    BULK_JOB_PARTIAL_MESSAGE,
                ),
            ]
        )

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refuse to delete a confirmed job."""
        if self.status not in UNCONFIRMED_BULK_STATUSES:
            raise ValidationError(BULK_JOB_DELETE_MESSAGE)
        return super().delete(*args, **kwargs)


class BulkRescheduleItemQuerySet(models.QuerySet):
    """Validates items created in bulk, as a preview does."""

    def bulk_create(self, objs, *args, **kwargs):
        """Validate each item first, which ``bulk_create`` would skip."""
        objs = list(objs)
        for obj in objs:
            obj.full_clean()
        return super().bulk_create(objs, *args, **kwargs)


class BulkRescheduleItem(BaseModel):
    """One hearing in a bulk move, with its planned date and what happened (spec 0023 #2.6).

    ``hearing_updated_at`` is the hearing's ``updated_at`` at preview: a
    hearing changed after it is skipped, so a preview never overwrites a later
    change (#8.3).
    """

    job = models.ForeignKey(BulkRescheduleJob, on_delete=models.CASCADE, related_name="items")
    hearing = models.ForeignKey(
        Hearing, on_delete=models.PROTECT, related_name="bulk_reschedule_items"
    )
    hearing_updated_at = models.DateTimeField(help_text="The hearing's last change at preview.")
    from_date = models.DateField()
    to_date = models.DateField()
    result = models.CharField(
        max_length=16, choices=BulkItemResult.choices, default=BulkItemResult.PENDING
    )
    error_code = models.CharField(max_length=16, blank=True)

    objects = BulkRescheduleItemQuerySet.as_manager()

    class Meta:
        """Meta options."""

        ordering = ("job", "to_date", "from_date")
        verbose_name = "Bulk reschedule item"
        verbose_name_plural = "Bulk reschedule items"
        constraints = [
            models.UniqueConstraint(
                fields=["job", "hearing"], name="hearings_bulk_item_one_per_hearing"
            ),
            models.CheckConstraint(
                check=~Q(from_date=F("to_date")),
                name="hearings_bulk_item_moves",
                violation_error_message=BULK_ITEM_MOVES_MESSAGE,
            ),
            models.CheckConstraint(
                check=Q(result__in=BulkItemResult.values),
                name="hearings_bulk_item_result_valid",
            ),
            models.CheckConstraint(
                check=Q(result=BulkItemResult.FAILED, error_code__regex=r"^E[0-9]{5}$")
                | (~Q(result=BulkItemResult.FAILED) & Q(error_code="")),
                name="hearings_bulk_item_error_code_iff_failed",
                violation_error_message=BULK_ITEM_ERROR_CODE_MESSAGE,
            ),
        ]

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.from_date} to {self.to_date}: {self.get_result_display()}"

    def clean(self):
        """Check the item against its job, and a new one against its hearing at preview.

        A finished item is final: the task processes only pending items, so a
        result set back to pending would move the hearing a second time.
        """
        super().clean()
        if not self.job_id:
            return
        job = self.job
        stored = None
        if not self._state.adding:
            stored = type(self).objects.filter(pk=self.pk).values_list("result", flat=True).first()
        finished = stored not in (None, BulkItemResult.PENDING)
        writes_result = not finished and self.result != BulkItemResult.PENDING
        rules = [
            ("result", not finished, BULK_ITEM_FINAL_MESSAGE),
            (
                "result",
                not writes_result or job.status == BulkRescheduleStatus.RUNNING,
                BULK_ITEM_RESULT_BEFORE_RUN_MESSAGE,
            ),
        ]
        if self._state.adding and self.hearing_id:
            hearing = self.hearing
            to_date_ok = (
                self.to_date == job.target_date
                if job.mode == BulkMode.TO_DATE
                else bool(job.schedule_after and self.to_date and self.to_date > job.schedule_after)
            )
            rules += [
                ("hearing", hearing.court_id == job.court_id, BULK_ITEM_COURT_MESSAGE),
                ("hearing", hearing.status in MOVABLE_STATUSES, NOT_MOVABLE_MESSAGE),
                ("from_date", self.from_date == hearing.hearing_date, FROM_DATE_MESSAGE),
                (
                    "to_date",
                    to_date_ok,
                    BULK_ITEM_TARGET_DATE_MESSAGE
                    if job.mode == BulkMode.TO_DATE
                    else BULK_ITEM_AFTER_DATE_MESSAGE,
                ),
                (
                    "hearing_updated_at",
                    self.hearing_updated_at == hearing.updated_at,
                    BULK_ITEM_SNAPSHOT_MESSAGE,
                ),
            ]
        _raise_broken_rules(rules)

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
            # isnull=False: NULL >= 1 is NULL, and a NULL CHECK passes.
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
