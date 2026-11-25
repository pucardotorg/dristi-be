"""The court-side steps on a process: when each applies and which action it needs (#4, #2.1).

One table serves every reader. The services refuse a step that does not
apply (``check``); responses offer only steps that apply and the caller is
allowed (``allowed_steps``); the lists filter on the same conditions
(``my_move_filter``). Each condition is written once, as a query and as a
test of a loaded process, side by side, so the two cannot drift apart
unnoticed (``tests/test_steps.py`` checks them against each other).
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import reduce
from operator import and_, or_

from django.db.models import Q

from apps.api.errors import BusinessError, ErrorCode

from . import court_actions as actions
from . import errors, ports
from .enums import LIVE_STATUSES, ProcessStatus, Step, StepMode


@dataclass(frozen=True)
class Condition:
    """One thing a step needs, as a query and as a test; ``error`` when it is not met."""

    where: Q
    holds: Callable[[object], bool]
    error: ErrorCode = errors.INVALID_PROCESS_ACTION


def status_in(*statuses):
    return Condition(Q(status__in=statuses), lambda process: process.status in statuses)


def channel_has(field, value, error):
    return Condition(
        Q(**{f"channel__{field}": value}),
        lambda process: getattr(process.channel, field) == value,
        error,
    )


ENVELOPE_PENDING = Condition(
    Q(envelope_received_at__isnull=True), lambda process: process.envelope_received_at is None
)


@dataclass(frozen=True)
class StepRule:
    """What a step needs, in the order its refusals are reported, and the action it checks.

    ``is_move`` marks the steps that advance a process: the caller's next
    move in the lists (``SGN-02``). Recall ends a process instead.
    """

    action: str
    conditions: tuple[Condition, ...]
    is_move: bool = True

    @property
    def where(self):
        return reduce(and_, (condition.where for condition in self.conditions))


STEPS = {
    Step.RECEIVE_ENVELOPE: StepRule(
        actions.RECEIVE_ENVELOPE,
        (
            channel_has("needs_envelope", True, errors.NO_ENVELOPE_FOR_CHANNEL),
            status_in(ProcessStatus.PENDING_STEPS),
            ENVELOPE_PENDING,
        ),
    ),
    # A system send goes through the channel's backend, which comes with that work.
    Step.SEND: StepRule(
        actions.SEND,
        (
            status_in(ProcessStatus.SIGNED),
            channel_has("send_mode", StepMode.MANUAL, errors.INVALID_PROCESS_ACTION),
        ),
    ),
    Step.RECORD_OUTCOME: StepRule(
        actions.RECORD_OUTCOME,
        (
            channel_has("status_mode", StepMode.MANUAL, errors.OUTCOME_RECORDED_BY_SYSTEM),
            status_in(ProcessStatus.SENT),
        ),
    ),
    Step.RECALL: StepRule(actions.RECALL, (status_in(*LIVE_STATUSES),), is_move=False),
}


def applicable_steps(process):
    """The steps that apply to the process in its current state, whoever asks."""
    return [
        step
        for step, rule in STEPS.items()
        if all(condition.holds(process) for condition in rule.conditions)
    ]


def _can(user, process, action):
    return ports.can(
        user,
        action,
        process.round.court_id,
        process_type=process.process_type.code,
        channel=process.channel.code,
    )


def allowed_steps(user, process):
    """The steps the caller may take on the process now (``allowed_actions``, ``RLE-07``)."""
    return [step for step in applicable_steps(process) if _can(user, process, STEPS[step].action)]


class StepNotApplicable(BusinessError):  # noqa: N818
    """The step does not apply to the process now; the message says what it can do instead."""

    def __init__(self, process, step, error):
        self.allowed_actions = [str(each) for each in applicable_steps(process)]
        status = process.get_status_display().lower()
        message = error.message
        if error is errors.INVALID_PROCESS_ACTION:
            message = f"A process that is {status} cannot be given the step {step.label.lower()}."
        if self.allowed_actions:
            message += f" Allowed now: {', '.join(self.allowed_actions)}."
        super().__init__(error, message)


def check(user, process, step):
    """Refuse a step the caller may not take (``403 E12015``) or that does not apply (``409``).

    The action is checked first: a caller without it learns nothing of the
    process's state.
    """
    rule = STEPS[step]
    if not _can(user, process, rule.action):
        raise BusinessError(errors.PROCESS_ACTION_NOT_ALLOWED)
    for condition in rule.conditions:
        if not condition.holds(process):
            raise StepNotApplicable(process, step, condition.error)


def my_move_filter(user, court_id):
    """A filter for the processes whose next step the caller may take at the court (``SGN-02``).

    PLACEHOLDER scope: the held actions are unscoped until spec 0029's
    grants, which add each grant's process types and channels to its term.
    """
    held = ports.held_actions(user, court_id)
    terms = [rule.where for rule in STEPS.values() if rule.is_move and rule.action in held]
    return reduce(or_, terms) if terms else Q(pk__in=[])
