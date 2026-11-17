"""Fixing a date: the orders contract (spec 0023 #7).

Called in-process by the orders module; there is no REST endpoint that
schedules a hearing. A date typed into a draft order is held as a
``PROVISIONAL`` hearing, counted in the day's load and invisible to parties;
it becomes ``SCHEDULED`` only when the order is triggered (``NXT-10``).
Raises the exceptions of ``apps.hearings.exceptions``, which the orders module
maps to its own API errors.

Court staff's one direct cancel, ``LISTED_IN_ERROR``, is here too and raises
API errors, as it is called by a view.
"""

import uuid
from dataclasses import dataclass, field

from django.db import transaction
from django.utils import timezone

from apps.cases.selectors import get_listability

from .. import conf, errors, exceptions, signals
from ..enums import (
    MOVABLE_STATUSES,
    CancellationReason,
    ChangeSource,
    HearingStatus,
    ReleaseReason,
    RescheduleReason,
    Side,
)
from ..models import Hearing
from . import calendar, notifications, reschedule
from .common import (
    SoftWarning,
    display_date,
    lock_hearing,
    record_scheduled_on_commit,
    require_transition,
    require_unmodified_since,
    save_hearing,
    send_on_commit,
)

# Released by the orders module; CONSUMED and CASE_CLOSED are set here only.
CALLER_RELEASE_REASONS = (ReleaseReason.DRAFT_DISCARDED, ReleaseReason.DATE_REMOVED)
# The statuses an order can be passed in (``ORD-05``): on the board.
ORDER_STATUSES = (
    HearingStatus.SCHEDULED,
    HearingStatus.IN_PROGRESS,
    HearingStatus.PASSED_OVER,
    HearingStatus.COMPLETED,
    HearingStatus.ABANDONED,
)


@dataclass(frozen=True)
class HoldResult:
    """The held hearing, soft warnings, and the date's load including the hold (``NXT-11``)."""

    hearing: Hearing
    warnings: list = field(default_factory=list)
    load: calendar.DayLoad | None = None


def _require_purpose(purpose_code):
    purpose, problem = calendar.purpose_problem(purpose_code)
    if problem:
        raise exceptions.InvalidPurpose()
    return purpose


def _require_date(court_id, hearing_date, previous_date=None):
    problems = calendar.date_problems(court_id, hearing_date, previous_date=previous_date)
    if problems:
        raise exceptions.InvalidHearingDate(problems[0])


def _hold_warnings(hearing, load, full):
    """Soft problems of a hold: a full day, a case already listed or held elsewhere, adjournments."""
    warnings = []
    if full:
        if conf.capacity_mode() == conf.CAPACITY_BLOCK:
            raise exceptions.CourtDayFull()
        warnings.append(calendar.full_day_warning(load))
    if hearing.moves_hearing_id is None:
        scheduled = Hearing.objects.filter(
            case_id=hearing.case_id, status=HearingStatus.SCHEDULED
        ).first()
        if scheduled:
            warnings.append(
                SoftWarning(
                    code="CASE_ALREADY_SCHEDULED",
                    message=(
                        "This case is already scheduled for "
                        f"{display_date(scheduled.hearing_date)}; this order cannot be "
                        "triggered until that hearing is heard, moved or cancelled."
                    ),
                    detail={
                        "hearing_id": str(scheduled.pk),
                        "hearing_date": str(scheduled.hearing_date),
                    },
                )
            )
    other_holds = (
        Hearing.objects.filter(case_id=hearing.case_id, status=HearingStatus.PROVISIONAL)
        .exclude(pk=hearing.pk)
        .values_list("source_order_id", flat=True)
    )
    if other_holds:
        warnings.append(
            SoftWarning(
                code="CASE_HELD_BY_ANOTHER_ORDER",
                message="Another draft order also holds a next hearing date for this case.",
                detail={"order_ids": [str(order_id) for order_id in other_holds]},
            )
        )
    return warnings + reschedule.adjournment_warnings(hearing.case_id)


def _require_moves_something(original, hearing_date, purpose):
    """A held move must change the original hearing's date or purpose (``E10012``)."""
    if (original.hearing_date, original.purpose_id) == (hearing_date, purpose.pk):
        raise exceptions.HearingError(
            f"The hearing to move is already on {display_date(hearing_date)} for "
            f"{purpose.label}. Change the date or the purpose.",
            error=errors.NOTHING_TO_CHANGE,
        )


def _current_hold(order_id, *, lock=False):
    queryset = Hearing.objects.select_related("purpose").filter(
        source_order_id=order_id, status=HearingStatus.PROVISIONAL
    )
    if lock:
        queryset = queryset.select_for_update()
    return queryset.first()


def hold(
    *,
    case_id,
    hearing_date,
    purpose_code,
    order_id,
    previous_hearing_id=None,
    moves_hearing_id=None,
    actor=None,
):
    """Hold a date typed into a draft order as a ``PROVISIONAL`` hearing (#7.1).

    Nothing is announced: no notification, signal or case-stage call. Holding
    for an order that already holds a date behaves as ``change``. Raises
    ``CaseNotListable``, ``InvalidPurpose``, ``InvalidHearingDate`` and, in
    ``block`` mode, ``CourtDayFull``. ``moves_hearing_id`` holds a
    *Rescheduling of hearing date* item: the original stays on its date until
    the order is triggered.
    """
    if _current_hold(order_id) is not None:
        return change(
            order_id=order_id, hearing_date=hearing_date, purpose_code=purpose_code, actor=actor
        )
    if _hold_for(order_id)[1] == "confirmed":
        raise exceptions.HearingError(
            "This order has already been triggered; its next hearing date can no longer change.",
            error=errors.INVALID_TRANSITION,
        )
    listability = get_listability(case_id)
    if not listability.listable:
        raise exceptions.CaseNotListable(listability.reason)
    court_id = listability.court_id
    purpose = _require_purpose(purpose_code)
    previous = None
    if previous_hearing_id:
        previous = Hearing.objects.get(pk=previous_hearing_id, case_id=case_id)
    moves = None
    if moves_hearing_id:
        moves = Hearing.objects.get(pk=moves_hearing_id, case_id=case_id)
        if moves.status not in MOVABLE_STATUSES:
            raise exceptions.HearingError(
                f"The hearing to move is {moves.get_status_display().lower()}; only a "
                "scheduled, passed-over or abandoned hearing can be moved.",
                error=errors.INVALID_TRANSITION,
            )
        _require_moves_something(moves, hearing_date, purpose)
    _require_date(court_id, hearing_date, previous.hearing_date if previous else None)

    with transaction.atomic():
        calendar.lock_court(court_id)
        load, full = calendar.capacity_check(court_id, hearing_date)
        hearing = Hearing(
            case_id=case_id,
            court_id=court_id,
            purpose=purpose,
            hearing_date=hearing_date,
            status=HearingStatus.PROVISIONAL,
            source_order_id=order_id,
            previous_hearing=previous,
            moves_hearing=moves,
        )
        warnings = _hold_warnings(hearing, load, full)
        save_hearing(hearing, actor, "held by draft order")
    return HoldResult(
        hearing=hearing, warnings=warnings, load=calendar.day_load(court_id, hearing_date)
    )


def change(*, order_id, hearing_date=None, purpose_code=None, actor=None):
    """Move the order's hold in place: date, purpose or both (#7.2).

    No ``HearingDateChange``: nothing announced has moved. Raises
    ``HoldNotFound``, ``InvalidPurpose``, ``InvalidHearingDate`` and
    ``CourtDayFull`` (block mode).
    """
    current = _current_hold(order_id)
    if current is None:
        raise exceptions.HoldNotFound()
    purpose = current.purpose if not purpose_code else _require_purpose(purpose_code)
    hearing_date = hearing_date or current.hearing_date
    previous_date = current.previous_hearing.hearing_date if current.previous_hearing_id else None
    if hearing_date != current.hearing_date:
        _require_date(current.court_id, hearing_date, previous_date)
    if current.moves_hearing_id:
        _require_moves_something(current.moves_hearing, hearing_date, purpose)

    with transaction.atomic():
        calendar.lock_court(current.court_id)
        hearing = _current_hold(order_id, lock=True)
        if hearing is None:
            raise exceptions.HoldNotFound()
        load, full = calendar.capacity_check(
            hearing.court_id, hearing_date, exclude_ids=[hearing.pk]
        )
        hearing.hearing_date = hearing_date
        hearing.purpose = purpose
        warnings = _hold_warnings(hearing, load, full)
        save_hearing(hearing, actor, "changed in draft order")
    return HoldResult(
        hearing=hearing, warnings=warnings, load=calendar.day_load(hearing.court_id, hearing_date)
    )


def release(*, order_id, reason, actor=None):
    """Release the order's hold: the draft was discarded or its date removed (#7.4).

    Idempotent: an order that holds nothing (any more) is a no-op.
    """
    if reason not in CALLER_RELEASE_REASONS:
        raise ValueError(f"Release reason must be one of {', '.join(CALLER_RELEASE_REASONS)}.")
    current = _current_hold(order_id)
    if current is None:
        return
    with transaction.atomic():
        calendar.lock_court(current.court_id)
        hearing = _current_hold(order_id, lock=True)
        if hearing is None:
            return
        _release(hearing, reason, actor)


def _release(hearing, reason, actor):
    hearing.status = HearingStatus.RELEASED
    hearing.release_reason = reason
    save_hearing(hearing, actor, f"released: {ReleaseReason(reason).label}")


def _hold_for(order_id):
    """Return ``(hold, outcome)`` for the order.

    ``outcome`` is ``"held"``, ``"confirmed"`` (the hearing this order
    already scheduled or moved), ``"released"`` or ``"missing"``.
    """
    held = _current_hold(order_id)
    if held is not None:
        return held, "held"
    rows = list(
        Hearing.objects.select_related("purpose", "moves_hearing__purpose")
        .filter(source_order_id=order_id)
        .order_by("-updated_at")
    )
    for row in rows:
        if row.status == HearingStatus.RELEASED and row.release_reason == ReleaseReason.CONSUMED:
            return row.moves_hearing, "confirmed"
        if row.status not in (HearingStatus.PROVISIONAL, HearingStatus.RELEASED):
            return row, "confirmed"
    if rows:
        return rows[0], "released"
    return None, "missing"


def _confirm_problems(hearing, today):
    """Why the hold can no longer be confirmed (#7.3 steps 2-3); ``[]`` when it can."""
    problems = []
    listability = get_listability(hearing.case_id)
    if not listability.listable:
        problems.append(
            calendar.Problem.of(
                errors.CASE_NOT_LISTABLE,
                exceptions.not_listable_message(listability.reason),
                field="case",
            )
        )
    if hearing.hearing_date < today:
        problems.append(
            calendar.Problem.of(
                errors.DATE_IN_PAST,
                f"The held date, {display_date(hearing.hearing_date)}, has passed. "
                "Choose a new date in the order.",
            )
        )
    not_sitting = calendar.not_sitting_problem(hearing.court_id, hearing.hearing_date)
    if not_sitting:
        problems.append(not_sitting)
    if hearing.moves_hearing_id is None:
        scheduled = Hearing.objects.filter(
            case_id=hearing.case_id, status=HearingStatus.SCHEDULED
        ).first()
        if scheduled is not None:
            problems.append(
                calendar.Problem.of(
                    errors.CASE_ALREADY_SCHEDULED,
                    f"The case is already scheduled for {display_date(scheduled.hearing_date)}. "
                    "Move that hearing instead of fixing a new date.",
                    field="case",
                )
            )
    else:
        original = hearing.moves_hearing
        if original.status not in MOVABLE_STATUSES:
            problems.append(
                calendar.Problem.of(
                    errors.INVALID_TRANSITION,
                    f"The hearing to move is now {original.get_status_display().lower()} and "
                    "can no longer be moved.",
                    field="moves_hearing",
                )
            )
        elif (original.hearing_date, original.purpose_id) == (
            hearing.hearing_date,
            hearing.purpose_id,
        ):
            problems.append(calendar.Problem.of(errors.NOTHING_TO_CHANGE))
        elif other := reschedule.other_scheduled(original):
            problems.append(
                calendar.Problem.of(
                    errors.CASE_ALREADY_SCHEDULED,
                    f"The case is already scheduled for {display_date(other.hearing_date)}.",
                    field="case",
                )
            )
    return problems


def _raise_confirm_failure(hearing, problems):
    """Raise ``HoldInvalid``; or ``CaseAlreadyScheduled`` when that is the only problem (#7.3).

    Step 2 (listability, the date) is checked before step 3 (the case's
    scheduled hearing), so any step-2 problem wins.
    """
    if all(problem.error == errors.CASE_ALREADY_SCHEDULED for problem in problems):
        scheduled = (
            Hearing.objects.filter(case_id=hearing.case_id, status=HearingStatus.SCHEDULED)
            .exclude(pk=hearing.moves_hearing_id)
            .values_list("pk", flat=True)
            .first()
        )
        raise exceptions.CaseAlreadyScheduled(scheduled, problems[0].message)
    raise exceptions.HoldInvalid(problems)


def validate(*, order_id):
    """Return why the order's date could not be confirmed now, without writing (#7.3).

    ``[]`` when it can, or when this order already confirmed it. The orders
    module refuses *Send for signing* on any problem (``SND-03``).
    """
    hearing, outcome = _hold_for(order_id)
    if outcome == "missing":
        return [calendar.Problem.of(errors.HOLD_NOT_FOUND, field="order")]
    if outcome == "released":
        return [calendar.Problem.of(errors.HOLD_RELEASED, field="order")]
    if outcome == "confirmed":
        return []
    return _confirm_problems(hearing, calendar.business_date())


def confirm(
    *,
    order_id,
    actor=None,
    reason_code=RescheduleReason.JUDICIAL_DIRECTION,
    reason_text="",
    sought_by=Side.COURT,
):
    """Make the order's held date a scheduled hearing: the order was triggered (#7.3).

    Called first among the order's workflows. Idempotent: a retried trigger
    returns the same hearing. Capacity is not re-checked; listability,
    sitting day and business date are (``HoldInvalid``). A case that already
    has a scheduled hearing raises ``CaseAlreadyScheduled``.

    A new date becomes ``SCHEDULED`` with the next serial number. A held move
    instead moves the original hearing in place, with ``source = ORDER`` and the
    order item's ``reason_code``, ``reason_text`` and ``sought_by``, and the
    hold is released as ``CONSUMED``; the original is returned.

    After commit: the case-stage call, ``hearing_scheduled`` or
    ``hearing_rescheduled``, and the parties' notification.
    """
    hearing, outcome = _hold_for(order_id)
    if outcome == "missing":
        raise exceptions.HoldNotFound()
    if outcome == "released":
        raise exceptions.HoldReleased(hearing.release_reason)
    if outcome == "confirmed":
        return hearing

    with transaction.atomic():
        calendar.lock_court(hearing.court_id)
        ids = sorted(filter(None, [hearing.pk, hearing.moves_hearing_id]))
        list(Hearing.objects.select_for_update().filter(pk__in=ids).order_by("pk"))
        hearing = _current_hold(order_id)
        if hearing is None:
            return confirm(
                order_id=order_id,
                actor=actor,
                reason_code=reason_code,
                reason_text=reason_text,
                sought_by=sought_by,
            )
        problems = _confirm_problems(hearing, calendar.business_date())
        if problems:
            _raise_confirm_failure(hearing, problems)
        now = timezone.now()
        if hearing.moves_hearing_id is None:
            hearing.status = HearingStatus.SCHEDULED
            hearing.sequence = calendar.next_sequence(hearing.court_id, hearing.hearing_date)
            hearing.confirmed_at = now
            save_hearing(hearing, actor, "confirmed: order triggered")
            record_scheduled_on_commit(hearing)
            send_on_commit(
                signals.hearing_scheduled, hearing_id=hearing.pk, case_id=hearing.case_id
            )
            _notify_scheduled(hearing)
            return hearing

        original = lock_hearing(hearing.moves_hearing_id)
        reschedule.move(
            original,
            to_date=hearing.hearing_date,
            to_purpose=hearing.purpose,
            reason_code=reason_code,
            reason_text=reason_text,
            sought_by=sought_by,
            source=ChangeSource.ORDER,
            source_ref=order_id,
            actor=actor,
        )
        _release(hearing, ReleaseReason.CONSUMED, actor)
        return original


def _notify_scheduled(hearing):
    court = hearing.court
    notifications.notify_on_commit(
        hearing.case_id,
        notifications.HEARING_SCHEDULED,
        {
            **notifications.case_context(hearing.case_id),
            "hearing_date": hearing.hearing_date.isoformat(),
            "sitting_time": conf.sitting_time(court.code.lower()),
            "purpose": hearing.purpose.label,
            "court": court.name,
            "mode": hearing.get_mode_display(),
        },
    )


def attach_order(*, hearing_id, order_id, actor=None):
    """Record the order passed in this hearing (``ORD-05``, ``HRG-12``).

    The order belongs to a hearing on the board. Attaching the same order
    again is a no-op; a hearing that already has another order is refused.
    """
    order_id = uuid.UUID(str(order_id))
    with transaction.atomic():
        hearing = lock_hearing(hearing_id)
        if hearing.order_id == order_id:
            return
        if hearing.status not in ORDER_STATUSES:
            raise exceptions.HearingError(
                "An order can be passed only in a hearing on the board, not in one that is "
                f"{hearing.get_status_display().lower()}.",
                error=errors.INVALID_TRANSITION,
            )
        if hearing.order_id is not None:
            raise exceptions.HearingError(
                f"This hearing already has another order ({hearing.order_id}).",
                error=errors.INVALID_TRANSITION,
            )
        hearing.order_id = order_id
        save_hearing(hearing, actor, "order attached")


def cancel_open_hearings(*, case_id, reason, order_id=None, actor=None):
    """The case leaves the court's list: cancel its open hearings, release its holds (#7.6).

    Called last among a triggered case-closing order's workflows. Scheduled,
    passed-over and abandoned hearings are cancelled; holds are released as
    ``CASE_CLOSED``, except the one held by ``order_id`` itself. A hearing in
    progress is left alone: the order was passed in it. Returns the hearings
    changed.
    """
    if reason not in CancellationReason.values:
        raise ValueError(f"Unknown cancellation reason {reason!r}.")
    courts = sorted(
        set(
            Hearing.objects.filter(
                case_id=case_id, status__in=(*MOVABLE_STATUSES, HearingStatus.PROVISIONAL)
            ).values_list("court_id", flat=True)
        )
    )
    changed = []
    with transaction.atomic():
        for court_id in courts:
            calendar.lock_court(court_id)
        hearings = (
            Hearing.objects.select_for_update()
            .select_related("purpose")
            .filter(case_id=case_id, status__in=(*MOVABLE_STATUSES, HearingStatus.PROVISIONAL))
            .order_by("pk")
        )
        now = timezone.now()
        for hearing in hearings:
            if hearing.status == HearingStatus.PROVISIONAL:
                if order_id is not None and hearing.source_order_id == order_id:
                    continue
                _release(hearing, ReleaseReason.CASE_CLOSED, actor)
            else:
                _cancel(hearing, reason, now, actor)
            changed.append(hearing)
    return changed


def _cancel(hearing, reason, now, actor):
    hearing.status = HearingStatus.CANCELLED
    hearing.cancelled_at = now
    hearing.cancellation_reason = reason
    save_hearing(hearing, actor, f"cancelled: {CancellationReason(reason).label}")
    send_on_commit(
        signals.hearing_cancelled, hearing_id=hearing.pk, case_id=hearing.case_id, reason=reason
    )
    notifications.notify_on_commit(
        hearing.case_id,
        notifications.HEARING_CANCELLED,
        {
            **notifications.case_context(hearing.case_id),
            "hearing_date": hearing.hearing_date.isoformat(),
        },
    )


def cancel_listed_in_error(*, hearing_id, actor=None, court_id=None, if_unmodified_since=None):
    """Court staff cancel one hearing listed in error; the only direct cancel (#7.6).

    Raises ``409 E10001`` unless the hearing is scheduled, passed over or
    abandoned, and ``412 E10002`` when stale.
    """
    lookup = Hearing.objects.filter(pk=hearing_id)
    if court_id is not None:
        lookup = lookup.filter(court_id=court_id)
    court = lookup.values_list("court_id", flat=True).get()
    with transaction.atomic():
        calendar.lock_court(court)
        hearing = lock_hearing(hearing_id, court)
        require_unmodified_since(hearing, if_unmodified_since)
        require_transition(hearing, "cancel", calendar.business_date())
        _cancel(hearing, CancellationReason.LISTED_IN_ERROR, timezone.now(), actor)
    return hearing
