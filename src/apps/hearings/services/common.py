"""Helpers every hearings service shares: transitions, saving, side effects (spec 0023 #3, #11).

Not part of the contract other modules use.
"""

import logging
from dataclasses import dataclass, field
from functools import partial

from django.db import transaction

from apps.api.errors import BusinessError
from apps.cases.services import record_hearing_scheduled

from .. import errors, signals
from ..enums import ATTENDANCE_STATUSES, MOVABLE_STATUSES, HearingStatus
from ..models import Hearing

logger = logging.getLogger(__name__)

# Action -> the statuses it may be taken from (#3). Hold, change, confirm and
# release act on provisional rows and are checked in ``listing``.
TRANSITIONS = {
    "start": (HearingStatus.SCHEDULED, HearingStatus.PASSED_OVER),
    "pass_over": (HearingStatus.SCHEDULED, HearingStatus.IN_PROGRESS),
    "end": (HearingStatus.IN_PROGRESS,),
    "abandon": (HearingStatus.SCHEDULED, HearingStatus.IN_PROGRESS, HearingStatus.PASSED_OVER),
    "reschedule": MOVABLE_STATUSES,
    "cancel": MOVABLE_STATUSES,
}
# Actions a user takes on the board; ``abandon`` is the midnight sweep's alone.
USER_ACTIONS = ("start", "pass_over", "end", "reschedule", "cancel")
# How each action reads in a message: "A completed hearing cannot be <done>."
ACTION_DONE = {
    "start": "started",
    "pass_over": "passed over",
    "end": "ended",
    "reschedule": "moved",
    "cancel": "cancelled",
    "mark_attendance": "marked for attendance",
}
SIGNAL_NAMES = {
    signals.hearing_scheduled: "hearing_scheduled",
    signals.hearing_rescheduled: "hearing_rescheduled",
    signals.hearing_ended: "hearing_ended",
    signals.hearing_cancelled: "hearing_cancelled",
}


def display_date(date):
    """A date as messages show it: ``16 Nov 2026``."""
    return f"{date.day} {date:%b %Y}"


def join_words(words, conjunction="or"):
    """``a``, ``a or b``, ``a, b or c``."""
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return f"{', '.join(words[:-1])} {conjunction} {words[-1]}"


@dataclass(frozen=True)
class SoftWarning:
    """A soft problem returned with a result, never raised (#10.6)."""

    code: str
    message: str
    detail: dict = field(default_factory=dict)


def allowed_actions(hearing, business_date):
    """Return the user actions the hearing's status and date allow, in board order.

    Roles are not applied here: the caller filters by the roles it holds in the
    hearing's court (#10.2). ``mark_attendance`` is added while attendance is open.
    """
    actions = [action for action in USER_ACTIONS if hearing.status in TRANSITIONS[action]]
    if "start" in actions and hearing.hearing_date != business_date:
        actions.remove("start")
    if attendance_open(hearing):
        actions.append("mark_attendance")
    return actions


def attendance_open(hearing):
    """Whether attendance can be marked: started, and its order not yet triggered (#6.5)."""
    return (
        hearing.status in ATTENDANCE_STATUSES
        and hearing.started_at is not None
        and hearing.attendance_locked_at is None
    )


class TransitionError(BusinessError):
    """``409 E10001``, carrying the hearing's ``allowed_actions``."""

    def __init__(self, hearing, action, business_date):
        self.allowed_actions = allowed_actions(hearing, business_date)
        status = hearing.get_status_display().lower()
        message = f"A hearing that is {status} cannot be {ACTION_DONE[action]}."
        board_actions = [ACTION_DONE[a] for a in self.allowed_actions if a != "mark_attendance"]
        if board_actions:
            message += f" It can be {join_words(board_actions)}."
        super().__init__(errors.INVALID_TRANSITION, message)


def require_transition(hearing, action, business_date):
    """Raise ``E10001`` unless ``action`` may be taken from the hearing's status."""
    if hearing.status not in TRANSITIONS[action]:
        raise TransitionError(hearing, action, business_date)


def require_unmodified_since(hearing, if_unmodified_since):
    """Raise ``412 E10002`` if the hearing changed after ``if_unmodified_since``.

    The header has whole-second precision, so a hearing changed within the
    same second as the client's copy is not stale.
    """
    if if_unmodified_since is None:
        return
    if hearing.updated_at.replace(microsecond=0) > if_unmodified_since.replace(microsecond=0):
        raise BusinessError(errors.HEARING_STALE)


def lock_hearing(hearing_id, court_id=None):
    """Return the hearing with its row locked, re-read (#11.5).

    Raises ``Hearing.DoesNotExist`` when missing, or not of ``court_id``.
    """
    queryset = Hearing.objects.select_for_update().select_related("purpose")
    if court_id is not None:
        queryset = queryset.filter(court_id=court_id)
    return queryset.get(pk=hearing_id)


def save_hearing(hearing, actor, reason):
    """Save the hearing with who did it and why on its history row (#2.1, #8.2)."""
    if actor is not None and getattr(actor, "pk", None):
        hearing.updated_by = actor
        if hearing._state.adding:
            hearing.created_by = actor
        hearing._history_user = actor
    hearing._change_reason = reason[:100]
    hearing.save()


def send_on_commit(signal, **kwargs):
    """Send ``signal`` once the transaction commits; never on rollback (#11.6)."""
    transaction.on_commit(partial(_send, signal, kwargs))


def _send(signal, kwargs):
    for receiver, result in signal.send_robust(sender=Hearing, **kwargs):
        if isinstance(result, Exception):
            logger.error(
                "event=HEARING_SIGNAL_RECEIVER_FAILED signal=%s hearing=%s receiver=%s error=%s",
                SIGNAL_NAMES.get(signal, signal),
                kwargs.get("hearing_id"),
                getattr(receiver, "__qualname__", receiver),
                result,
            )


def record_scheduled_on_commit(hearing):
    """Tell the case module a hearing was scheduled, after commit (#7.5).

    A failure there is logged and never undoes the hearing.
    """
    transaction.on_commit(
        partial(_record_scheduled, hearing.case_id, hearing.purpose.code, hearing.hearing_date)
    )


def _record_scheduled(case_id, purpose_code, hearing_date):
    try:
        record_hearing_scheduled(
            case_id=case_id, purpose_code=purpose_code, hearing_date=hearing_date
        )
    except Exception:
        logger.exception(
            "event=CASE_HEARING_SCHEDULED_FAILED case=%s purpose=%s", case_id, purpose_code
        )


def ended_signal(hearing, abandoned=False):
    """Queue ``hearing_ended`` for an end or an abandonment."""
    send_on_commit(
        signals.hearing_ended,
        hearing_id=hearing.pk,
        case_id=hearing.case_id,
        abandoned=abandoned,
    )
