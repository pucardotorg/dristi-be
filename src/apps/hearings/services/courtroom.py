"""Running the courtroom: start, pass over, end, bulk actions, attendance, the board (spec 0023 #5, #6).

Every status change is timed: the history row records when, and leaving
``IN_PROGRESS`` adds the period to ``heard_duration`` (``HRG-08``). Start, pass
over and end take ``if_unmodified_since`` against ``updated_at`` (``412 E10002``).
"""

import logging
import uuid
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.cases.selectors import get_attendance_roll

from .. import errors
from ..enums import AttendanceMark, HearingStatus
from ..models import Hearing, HearingAttendance
from . import calendar
from .common import (
    TRANSITIONS,
    allowed_actions,
    attendance_open,
    display_date,
    ended_signal,
    join_words,
    lock_hearing,
    require_transition,
    require_unmodified_since,
    save_hearing,
)

logger = logging.getLogger(__name__)

BULK_END = "END"
BULK_PASS_OVER = "PASS_OVER"
BULK_ACTIONS = (BULK_END, BULK_PASS_OVER)


def _court_of(hearing_id, court_id=None):
    lookup = Hearing.objects.filter(pk=hearing_id)
    if court_id is not None:
        lookup = lookup.filter(court_id=court_id)
    return lookup.values_list("court_id", flat=True).get()


def _close_period(hearing, now):
    """Add the open in-progress period to ``heard_duration`` and close it."""
    if hearing.last_started_at is not None:
        hearing.heard_duration += now - hearing.last_started_at
    hearing.last_started_at = None


def _start(hearing, now, actor):
    hearing.status = HearingStatus.IN_PROGRESS
    hearing.started_at = hearing.started_at or now
    hearing.last_started_at = now
    save_hearing(hearing, actor, "started")


def _pass_over(hearing, now, actor):
    if hearing.status == HearingStatus.IN_PROGRESS:
        _close_period(hearing, now)
    hearing.status = HearingStatus.PASSED_OVER
    save_hearing(hearing, actor, "passed over")


def _end(hearing, now, actor, adjournment_sought_by=""):
    _close_period(hearing, now)
    hearing.status = HearingStatus.COMPLETED
    hearing.ended_at = now
    hearing.adjournment_sought_by = adjournment_sought_by or ""
    save_hearing(hearing, actor, "ended")
    ended_signal(hearing)


def _act(hearing_id, action, actor, court_id, if_unmodified_since, apply):
    court = _court_of(hearing_id, court_id)
    with transaction.atomic():
        calendar.lock_court(court)
        hearing = lock_hearing(hearing_id, court)
        require_unmodified_since(hearing, if_unmodified_since)
        today = calendar.business_date()
        require_transition(hearing, action, today)
        apply(hearing, today, timezone.now())
    return hearing


def start(*, hearing_id, actor=None, court_id=None, if_unmodified_since=None):
    """Call a scheduled or passed-over hearing: ``IN_PROGRESS`` (#6.1).

    Only on its date (``409 E10010``). Keeps the first ``started_at``.
    Several hearings of one court may be in progress at once (``HRG-06``).
    """

    def apply(hearing, today, now):
        _require_today(hearing, today, "started")
        _start(hearing, now, actor)

    return _act(hearing_id, "start", actor, court_id, if_unmodified_since, apply)


def _require_today(hearing, today, done):
    """Raise ``409 E10010`` unless the hearing is listed for ``today``."""
    if hearing.hearing_date != today:
        raise BusinessError(
            errors.HEARING_NOT_TODAY,
            f"This hearing is listed for {display_date(hearing.hearing_date)}. It can be "
            f"{done} only on that day, not today ({display_date(today)}).",
        )


def pass_over(*, hearing_id, actor=None, court_id=None, if_unmodified_since=None):
    """Set a hearing aside unheard, to be returned to later the same day (#6.2, ``HRG-04``).

    Only on its date (``409 E10010``): a future hearing is moved, not passed over.
    """

    def apply(hearing, today, now):
        _require_today(hearing, today, "passed over")
        _pass_over(hearing, now, actor)

    return _act(hearing_id, "pass_over", actor, court_id, if_unmodified_since, apply)


def end(
    *, hearing_id, adjournment_sought_by="", actor=None, court_id=None, if_unmodified_since=None
):
    """End a hearing in progress: ``COMPLETED`` (#6.3).

    Needs no order, complete or signed (``HRG-09``). ``adjournment_sought_by``
    is the side that sought the adjournment, empty when business was done.
    Starts nothing else (``HRG-02``).
    """
    return _act(
        hearing_id,
        "end",
        actor,
        court_id,
        if_unmodified_since,
        lambda hearing, today, now: _end(hearing, now, actor, adjournment_sought_by),
    )


@dataclass(frozen=True)
class BulkResult:
    """What a bulk action did: one entry per hearing, in ``done`` or ``skipped``."""

    done: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def bulk_action(*, court_id, hearing_ids, action, actor=None):
    """End or pass over several hearings in one press (#6.6, ``HRG-07``, ``CLS-10``).

    Ending a scheduled hearing starts and ends it at the same time, with no
    heard time; it must be listed for today. A hearing that cannot take the
    action is left as it is and reported under ``skipped`` with its
    ``allowed_actions``. One transaction, under the court lock.
    """
    if action not in BULK_ACTIONS:
        raise BusinessError(
            api_errors.INVALID,
            f"Choose {join_words(BULK_ACTIONS)} as the bulk action.",
            field="action",
        )
    hearing_ids = list(dict.fromkeys(str(pk) for pk in hearing_ids))
    result = BulkResult()
    with transaction.atomic():
        calendar.lock_court(court_id)
        hearings = {
            str(hearing.pk): hearing
            for hearing in Hearing.objects.select_for_update()
            .filter(pk__in=hearing_ids, court_id=court_id)
            .order_by("pk")
        }
        today = calendar.business_date()
        now = timezone.now()
        for hearing_id in hearing_ids:
            hearing = hearings.get(hearing_id)
            if hearing is None:
                result.skipped.append(
                    {
                        "hearing_id": hearing_id,
                        "code": api_errors.NOT_FOUND.code,
                        "allowed_actions": [],
                    }
                )
                continue
            skip = _bulk_skip(hearing, action, today)
            if skip:
                result.skipped.append(
                    {
                        "hearing_id": hearing.pk,
                        "code": skip,
                        "allowed_actions": allowed_actions(hearing, today),
                    }
                )
                continue
            if action == BULK_PASS_OVER:
                _pass_over(hearing, now, actor)
            elif hearing.status == HearingStatus.SCHEDULED:
                hearing.started_at = hearing.started_at or now
                hearing.last_started_at = None
                _end(hearing, now, actor)
            else:
                _end(hearing, now, actor)
            result.done.append({"hearing_id": hearing.pk, "status": hearing.status})
    return result


def _bulk_skip(hearing, action, today):
    """The error code a bulk action would hit on the hearing, or empty."""
    allowed = (
        TRANSITIONS["pass_over"]
        if action == BULK_PASS_OVER
        else (HearingStatus.SCHEDULED, HearingStatus.IN_PROGRESS)
    )
    if hearing.status not in allowed:
        return errors.INVALID_TRANSITION.code
    # Ending a scheduled hearing starts it, so both need its day; as single actions (#6.1, #6.2).
    same_day = action == BULK_PASS_OVER or hearing.status == HearingStatus.SCHEDULED
    if same_day and hearing.hearing_date != today:
        return errors.HEARING_NOT_TODAY.code
    return ""


# Attendance (#6.5)


def _roll_key(attendee_type, participant_id):
    return (str(attendee_type), str(participant_id))


def set_attendance(*, hearing_id, marks, actor=None):
    """Replace the hearing's whole attendance roll with ``marks`` (#6.5).

    ``marks`` are ``{attendee_type, participant_id, mark, appearance_mode}``;
    a person left out is unmarked and has no row. Every entry must be on the
    case's roll (``400 E10011``, ``field = marks[i]``). Allowed once the
    hearing has started and until its order is triggered (``409 E10022``).
    Returns the new rows.
    """
    with transaction.atomic():
        hearing = lock_hearing(hearing_id)
        if not attendance_open(hearing):
            raise BusinessError(errors.ATTENDANCE_LOCKED, _attendance_closed_message(hearing))
        roll = {
            _roll_key(entry.type, entry.participant_id)
            for entry in get_attendance_roll(hearing.case_id)
        }
        rows, seen = [], set()
        for index, mark in enumerate(marks):
            key = _roll_key(mark.get("attendee_type"), mark.get("participant_id"))
            if key in seen:
                raise BusinessError(
                    api_errors.INVALID,
                    "This person is marked more than once; keep one mark for them.",
                    field=f"marks[{index}]",
                )
            seen.add(key)
            if key not in roll:
                raise BusinessError(errors.NOT_ON_ROLL, field=f"marks[{index}]")
            row = HearingAttendance(
                hearing=hearing,
                attendee_type=mark["attendee_type"],
                participant_id=mark["participant_id"],
                mark=mark.get("mark", ""),
                appearance_mode=mark.get("appearance_mode") or "",
            )
            if actor is not None and getattr(actor, "pk", None):
                row.created_by = row.updated_by = actor
            # The roll and the hearing were checked once above; clean() would re-read
            # the roll for every row.
            row.clean_fields(exclude=["hearing"])
            _check_mode(row, index)
            rows.append(row)
        HearingAttendance.objects.filter(hearing=hearing).delete()
        HearingAttendance.objects.bulk_create(rows)
    return rows


def _attendance_closed_message(hearing):
    if hearing.attendance_locked_at is not None:
        return "Attendance is locked: the hearing's order has been triggered."
    if hearing.started_at is None:
        return "Attendance can be marked once the hearing has started."
    return (
        f"Attendance cannot be marked on a hearing that is {hearing.get_status_display().lower()}."
    )


def _check_mode(row, index):
    present = row.mark == AttendanceMark.PRESENT
    if present and not row.appearance_mode:
        raise BusinessError(
            api_errors.INVALID,
            "Choose in person or video for someone marked present.",
            field=f"marks[{index}].appearance_mode",
        )
    if not present and row.appearance_mode:
        raise BusinessError(
            api_errors.INVALID,
            "Leave the appearance mode empty for someone absent or not required.",
            field=f"marks[{index}].appearance_mode",
        )


def attendance_complete(hearing_id):
    """Whether every person on the case's roll is marked (``ATT-04``, ``SND-03``)."""
    hearing = Hearing.objects.only("case_id").get(pk=hearing_id)
    roll = {
        _roll_key(entry.type, entry.participant_id)
        for entry in get_attendance_roll(hearing.case_id)
    }
    marked = {
        _roll_key(attendee_type, participant_id)
        for attendee_type, participant_id in HearingAttendance.objects.filter(
            hearing_id=hearing_id
        ).values_list("attendee_type", "participant_id")
    }
    return roll <= marked


def lock_attendance(hearing_id, actor=None):
    """Freeze the roll: the hearing's order was triggered (#6.5). Idempotent."""
    with transaction.atomic():
        hearing = lock_hearing(hearing_id)
        if hearing.attendance_locked_at is not None:
            return hearing
        hearing.attendance_locked_at = timezone.now()
        save_hearing(hearing, actor, "attendance locked")
    return hearing


# The board (#5)


def reorder_board(*, court_id, hearing_date, hearing_ids, actor=None):
    """Put the day's waiting hearings in a new order (#5).

    ``hearing_ids`` must list every ``SCHEDULED`` hearing of the court and date
    exactly once (``400 E10019``). They take the serial numbers they already
    hold between them, in the new order; every other hearing keeps its own.
    """
    try:
        hearing_ids = [str(uuid.UUID(str(pk))) for pk in hearing_ids]
    except ValueError:
        raise BusinessError(errors.BOARD_MISMATCH, field="hearing_ids") from None
    with transaction.atomic():
        calendar.lock_court(court_id)
        waiting = list(
            Hearing.objects.select_for_update()
            .filter(court_id=court_id, hearing_date=hearing_date, status=HearingStatus.SCHEDULED)
            .order_by("pk")
        )
        by_id = {str(hearing.pk): hearing for hearing in waiting}
        if len(hearing_ids) != len(set(hearing_ids)) or set(hearing_ids) != set(by_id):
            raise BusinessError(errors.BOARD_MISMATCH, field="hearing_ids")
        sequences = sorted(hearing.sequence for hearing in waiting)
        # Park the waiting rows above every serial number on the day's board (heard
        # and passed-over ones included) first, so no two share one midway.
        top = (
            Hearing.objects.filter(court_id=court_id, hearing_date=hearing_date).aggregate(
                top=Max("sequence")
            )["top"]
            or 0
        ) + 1
        for offset, hearing in enumerate(waiting):
            Hearing.objects.filter(pk=hearing.pk).update(sequence=top + offset)
        for sequence, hearing_id in zip(sequences, hearing_ids, strict=True):
            hearing = by_id[hearing_id]
            hearing.sequence = sequence
            save_hearing(hearing, actor, "board reordered")
    return [by_id[hearing_id] for hearing_id in hearing_ids]


def board(court_id, hearing_date):
    """Return the day's board: every hearing on it, by ``status_order, sequence`` (#5)."""
    from ..enums import BOARD_STATUSES

    return list(
        Hearing.objects.select_related("purpose")
        .filter(court_id=court_id, hearing_date=hearing_date, status__in=BOARD_STATUSES)
        .order_by("status_order", "sequence")
    )


def current(court_id):
    """Return the court's hearings in progress today, by serial number (#6.4, ``HRG-10``)."""
    return list(
        Hearing.objects.select_related("purpose")
        .filter(
            court_id=court_id,
            hearing_date=calendar.business_date(),
            status=HearingStatus.IN_PROGRESS,
        )
        .order_by("sequence")
    )


def board_etag(court_id):
    """Return an ETag for the court's board today: it changes whenever any listing changes (#6.4).

    One indexed query: the count and the latest change of the day's listings.
    """
    today = calendar.business_date()
    state = Hearing.objects.filter(court_id=court_id, hearing_date=today).aggregate(
        n=Count("pk"), last=Max("updated_at")
    )
    last = state["last"].isoformat() if state["last"] else "-"
    return f'"{today.isoformat()}:{state["n"]}:{last}"'


# Midnight sweep (#11.4)


def end_day(court_id, day):
    """Abandon the court's hearings of ``day`` not finished: not reached (#11.4, ``HRG-05``).

    Scheduled, in-progress and passed-over hearings become ``ABANDONED`` with
    ``abandoned_at``; an open in-progress period is added to ``heard_duration``.
    No date is invented for them. Returns how many were abandoned.
    """
    with transaction.atomic():
        calendar.lock_court(court_id)
        hearings = (
            Hearing.objects.select_for_update()
            .filter(court_id=court_id, hearing_date=day, status__in=TRANSITIONS["abandon"])
            .order_by("pk")
        )
        now = timezone.now()
        count = 0
        for hearing in hearings:
            if hearing.status == HearingStatus.IN_PROGRESS:
                _close_period(hearing, now)
            hearing.status = HearingStatus.ABANDONED
            hearing.abandoned_at = now
            save_hearing(hearing, None, "abandoned at midnight")
            ended_signal(hearing, abandoned=True)
            count += 1
    if count:
        logger.info("event=HEARINGS_ABANDONED court=%s date=%s count=%s", court_id, day, count)
    return count


def end_days():
    """Run ``end_day`` for every court and every past day still holding open listings.

    Sweeping every day before the business date, not only yesterday, lets a
    missed run catch up. Returns the total abandoned.
    """
    pending = (
        Hearing.objects.filter(
            Q(status__in=TRANSITIONS["abandon"]), hearing_date__lt=calendar.business_date()
        )
        .values_list("court_id", "hearing_date")
        .distinct()
        .order_by("court_id", "hearing_date")
    )
    return sum(end_day(court_id, day) for court_id, day in pending)
