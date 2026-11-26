"""The *Application action* order item: every court act on an application (spec 0033 #8).

Onboarding, deferring review, setting or moving the decision date, inviting a
response, dismissing, accepting and rejecting are answers to one item's
questions (#8.2). ``apply`` is the handler's ``execute``: it runs when the order
is **triggered** (signed and its data complete, #8.4), under the application's
lock, idempotent on the order. There is no court endpoint of this module that
changes an application.

Until ``apps.orders`` exists (#1.2), ``apply`` is called by the admin action
*Record order on application* and by tests, with a stand-in order id.
"""

import datetime
import logging
from dataclasses import dataclass

from django.db import transaction

from apps.hearings import selectors as hearings

from .. import conf, ports
from ..enums import OPEN_STATUSES, Action, ApplicationStatus, Outcome, WorkflowStatus
from ..models import ApplicationTransition
from . import common, notifications, numbering, objections
from .calendar import today

logger = logging.getLogger(__name__)

S = ApplicationStatus

# In-process problem codes returned to the order module (#15.6), never E13 codes.
APPLICATION_NOT_OPEN = "APPLICATION_NOT_OPEN"
APPLICATION_NOT_IN_STATUS = "APPLICATION_NOT_IN_STATUS"
DATE_IN_PAST = "DATE_IN_PAST"
RESPOND_BY_INVALID = "RESPOND_BY_INVALID"
OUTCOME_NOT_ALLOWED = "OUTCOME_NOT_ALLOWED"
CIS_OUTCOME_INVALID = "CIS_OUTCOME_INVALID"
HEARING_MOVE_REQUIRED = "HEARING_MOVE_REQUIRED"
REQUIRED = "REQUIRED"
INVALID = "INVALID"


@dataclass(frozen=True)
class Problem:
    """As 0025 #1.2 ``Problem``: ``values.<key>`` or ``target_id``."""

    field: str
    code: str
    message: str


@dataclass(frozen=True)
class RunResult:
    """As 0025 #1.2 ``RunResult``."""

    status: str  # "DONE" or "FAILED"
    payload: dict
    error_code: str = ""


# Questions (#8.2) ---------------------------------------------------------------------


def _date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return False


def suggested_date(application):
    """The case's next hearing date when it is after today, else None (#10, ``ALC-10``)."""
    hearing = hearings.next_hearing(application.case_id)
    if hearing is not None and hearing.hearing_date > today():
        return hearing.hearing_date
    return None


def defaults(application):
    """Item defaults (#8.2, ``VAR-02``): ``[Application Number]``, ``[Application Type]``, answers."""
    bring_back_on = suggested_date(application)
    return {
        "application_number": application.application_number or "",
        "application_type": application.application_type.label,
        "onboard": True,
        "decides": False,
        "bring_back_on": bring_back_on.isoformat() if bring_back_on else None,
        "respond": True,
        "respond_by": (bring_back_on - datetime.timedelta(days=1)).isoformat()
        if bring_back_on
        else None,
    }


def asked(application, values, business_date=None):
    """Which questions are asked for these answers (#8.2 "Asked when")."""
    business_date = business_date or today()
    onboarded = application.onboarded_at is not None
    onboard = True if onboarded else bool(values.get("onboard"))
    decides = bool(values.get("decides"))
    bring_back_on = _date(values.get("bring_back_on"))
    respond_asked = (
        onboard
        and not decides
        and isinstance(bring_back_on, datetime.date)
        and bring_back_on > business_date
    )
    cis = conf.cis_outcomes(ports.state_code(application.case))
    return {
        "onboard": not onboarded,
        "outcome": decides,
        "cis_outcome": decides and cis is not None,
        "bring_back_on": not decides,
        "respond": respond_asked,
        "respond_by": respond_asked and bool(values.get("respond")),
    }


def unavailable_reason(application):
    """``APPLICATION_NOT_OPEN`` when the application is not before the court (#8.1, ``ITM-03``)."""
    if application.status not in OPEN_STATUSES:
        return APPLICATION_NOT_OPEN
    return None


def validate(application, values, *, complete, business_date=None, moves_hearing=False):
    """The item's answers against #8.2. Returns ``[Problem]``; empty when fine."""
    business_date = business_date or today()
    problems = []

    def problem(key, code, message):
        problems.append(Problem(f"values.{key}", code, message))

    if unavailable_reason(application):
        return [Problem("target_id", APPLICATION_NOT_OPEN, "The application is not open.")]
    onboarded = application.onboarded_at is not None
    onboard = True if onboarded else values.get("onboard")
    decides = values.get("decides")
    which = asked(application, values, business_date)
    outcome = values.get("outcome")
    bring_back_on = _date(values.get("bring_back_on"))
    respond_by = _date(values.get("respond_by"))

    if bring_back_on is False:
        problem("bring_back_on", INVALID, "Enter a date as YYYY-MM-DD.")
    elif which["bring_back_on"] and bring_back_on and bring_back_on < business_date:
        problem("bring_back_on", DATE_IN_PAST, "The date to bring it back cannot be in the past.")
    if respond_by is False:
        problem("respond_by", INVALID, "Enter a date as YYYY-MM-DD.")
    elif (
        which["respond_by"]
        and respond_by
        and (
            respond_by < business_date
            or (isinstance(bring_back_on, datetime.date) and respond_by > bring_back_on)
        )
    ):
        problem(
            "respond_by",
            RESPOND_BY_INVALID,
            "The respond-by date must be today or later, and not after the date to bring it back.",
        )
    if which["outcome"] and outcome:
        allowed = (Outcome.ACCEPTED, Outcome.REJECTED) if onboard else (Outcome.DISMISSED,)
        if outcome not in allowed:
            problem(
                "outcome",
                OUTCOME_NOT_ALLOWED,
                "An application not onboarded can only be dismissed; "
                "an onboarded one is accepted or rejected.",
            )
    if which["cis_outcome"] and values.get("cis_outcome"):
        codes = {item.get("code") for item in conf.cis_outcomes(ports.state_code(application.case))}
        if values["cis_outcome"] not in codes:
            problem("cis_outcome", CIS_OUTCOME_INVALID, "Choose a CIS outcome from the list.")

    if complete:
        for key, needed in (
            ("onboard", which["onboard"]),
            ("decides", True),
            ("outcome", which["outcome"]),
            ("cis_outcome", which["cis_outcome"]),
            ("bring_back_on", which["bring_back_on"]),
            ("respond", which["respond"]),
            ("respond_by", which["respond_by"]),
        ):
            if needed and values.get(key) in (None, ""):
                problem(key, REQUIRED, "This question must be answered.")
        if (
            decides
            and outcome == Outcome.ACCEPTED
            and application.spec.needs_hearing
            and not moves_hearing
        ):
            problem(
                "outcome",
                HEARING_MOVE_REQUIRED,
                "Accepting this application must move its hearing in the same order.",
            )
    return problems


def summary(application, values, *, number_replaced=None, business_date=None):
    """The line recorded on the application for this order (#4.4)."""
    onboarded = application.onboarded_at is not None
    onboard = values.get("onboard") and not onboarded
    decides = values.get("decides")
    parts = []
    if onboard:
        number = (number_replaced or {}).get("to") or application.application_number
        parts.append(f"Onboarded as {number}" if number else "Onboarded")
    if decides:
        parts.append(str(values.get("outcome", "")).capitalize())
    else:
        day = _date(values.get("bring_back_on"))
        if day:
            if not onboard and not onboarded:
                parts.append(f"Review deferred to {day:%d %b}")
            else:
                parts.append(f"to be decided on {day:%d %b}")
        if values.get("respond") and _date(values.get("respond_by")) and (onboard or onboarded):
            parts.append(f"response by {_date(values['respond_by']):%d %b}")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:]


# Executing (#8.3, #8.4) ----------------------------------------------------------------


def _already_applied(application_id, order_id):
    return ApplicationTransition.objects.filter(
        application_ref=application_id, order_id=order_id
    ).exists()


def apply(application_id, values, *, order_id, actor=None, order_date=None, moves_hearing=False):
    """Apply a triggered order's answers to the application (#8.3). Returns a ``RunResult``.

    Idempotent on the order: an order already applied returns its first result.
    If the application is no longer in a status the answers can act on, the run
    is ``FAILED`` with ``APPLICATION_NOT_IN_STATUS`` and nothing changes.
    """
    with transaction.atomic():
        application = common.lock(application_id)
        if _already_applied(application.pk, order_id):
            return RunResult("DONE", {"already_applied": True})
        business_date = order_date or today()
        problems = validate(
            application,
            values,
            complete=True,
            business_date=business_date,
            moves_hearing=moves_hearing,
        )
        if problems:
            code = (
                APPLICATION_NOT_IN_STATUS
                if problems[0].code == APPLICATION_NOT_OPEN
                else problems[0].code
            )
            logger.error(
                "event=APPLICATION_ORDER_RUN_REFUSED application_id=%s order_id=%s error_code=%s",
                application.pk,
                order_id,
                code,
            )
            return RunResult("FAILED", {}, code)
        result = _execute(application, values, order_id, actor, business_date)
    if result.payload.get("run_workflow"):
        from .workflows import enqueue

        enqueue(application.pk)
    return result


def _execute(application, values, order_id, actor, business_date):
    onboarded = application.onboarded_at is not None
    onboard = values.get("onboard") and not onboarded
    decides = values.get("decides")
    payload = {}
    number_replaced = None
    line = summary(application, values, business_date=business_date)

    if onboard:
        number_replaced = numbering.replace_on_onboarding(application)
        line = summary(
            application, values, number_replaced=number_replaced, business_date=business_date
        )
        application.onboarded_at = common.now()
        application.review_due_date = None
        ports.tasks.complete("review_application", application)
        if decides:
            application.decision_date = business_date
            numbering.guard_number_clash(
                lambda: common.transition(
                    application,
                    Action.ONBOARD,
                    actor,
                    to_status=S.PENDING_DECISION,
                    order_id=order_id,
                    summary=line.split("; ")[0],
                    metadata={
                        "number_replaced": number_replaced,
                        "decision_date": business_date.isoformat(),
                        "objections_invited": None,
                        "respond_by": None,
                    },
                )
            )
        else:
            _set_decision_date(application, values, business_date)
            numbering.guard_number_clash(
                lambda: common.transition(
                    application,
                    Action.ONBOARD,
                    actor,
                    to_status=S.PENDING_DECISION,
                    order_id=order_id,
                    summary=line,
                    metadata={
                        "number_replaced": number_replaced,
                        "decision_date": application.decision_date.isoformat(),
                        "objections_invited": application.objections_invited,
                        "respond_by": _iso(application.respond_by),
                    },
                )
            )
            ports.tasks.open("decide_application", application, due_date=application.decision_date)
            objections.after_date_set(application, previous_respond_by=None)
            return RunResult("DONE", {"status": application.status})

    if decides:
        outcome = values["outcome"]
        return _decide(application, outcome, values, order_id, actor, line, onboarded or onboard)

    if not onboarded:
        # Defer review (ALC-34): not onboarded, nothing decided.
        from_date = application.review_due_date
        application.review_due_date = _date(values["bring_back_on"])
        common.transition(
            application,
            Action.DEFER_REVIEW,
            actor,
            order_id=order_id,
            summary=line,
            metadata={"from_date": _iso(from_date), "to_date": _iso(application.review_due_date)},
        )
        ports.tasks.reschedule(
            "review_application", application, due_date=application.review_due_date
        )
        logger.info("event=APPLICATION_REVIEW_DEFERRED application_id=%s", application.pk)
        return RunResult("DONE", {"status": application.status})

    # Move the decision date (ALC-15).
    from_date, previous_respond_by = application.decision_date, application.respond_by
    _set_decision_date(application, values, business_date)
    common.transition(
        application,
        Action.MOVE_DECISION_DATE,
        actor,
        order_id=order_id,
        summary=line,
        metadata={
            "from_date": _iso(from_date),
            "to_date": _iso(application.decision_date),
            "objections_invited": application.objections_invited,
            "respond_by": _iso(application.respond_by),
        },
    )
    ports.tasks.reschedule("decide_application", application, due_date=application.decision_date)
    objections.after_date_set(application, previous_respond_by=previous_respond_by)
    notifications.decision_date_moved(application)
    logger.info("event=APPLICATION_DECISION_DATE_MOVED application_id=%s", application.pk)
    payload.update(status=application.status)
    return RunResult("DONE", payload)


def _set_decision_date(application, values, business_date):
    """``decision_date``, and the invitation from questions 6-7 when asked (#8.3).

    A date of today asks for no response (``ALC-11``): ``respond_by`` is cleared
    and an earlier invitation stays recorded as it was.
    """
    application.decision_date = _date(values["bring_back_on"])
    if asked(application, values, business_date)["respond"]:
        application.objections_invited = bool(values.get("respond"))
        application.respond_by = _date(values.get("respond_by")) if values.get("respond") else None
    else:
        application.respond_by = None


def _decide(application, outcome, values, order_id, actor, line, onboarded):
    action = {
        Outcome.ACCEPTED: Action.ACCEPT,
        Outcome.REJECTED: Action.REJECT,
        Outcome.DISMISSED: Action.DISMISS,
    }[outcome]
    if action == Action.DISMISS:
        ports.tasks.complete("review_application", application)
    else:
        ports.tasks.complete("decide_application", application)
    application.outcome = outcome
    application.deciding_order_id = order_id
    if outcome == Outcome.ACCEPTED and application.spec.has_workflow:
        application.workflow_status = WorkflowStatus.PENDING
    elif outcome == Outcome.REJECTED and application.spec.runs_on_reject:
        application.workflow_status = WorkflowStatus.PENDING
    metadata = {}
    if values.get("cis_outcome"):
        metadata["cis_outcome"] = values["cis_outcome"]
    common.transition(
        application,
        action,
        actor,
        to_status=S(outcome),
        order_id=order_id,
        summary=line,
        metadata=metadata,
    )
    objections.close_open_objection(application)
    if action == Action.DISMISS:
        notifications.dismissed(application)
    else:
        notifications.decided(application)
    return RunResult(
        "DONE",
        {
            "status": application.status,
            "run_workflow": application.workflow_status == WorkflowStatus.PENDING,
        },
    )


def _iso(day):
    return day.isoformat() if day else None
