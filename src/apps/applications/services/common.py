"""The one place a status changes (spec 0033 #1, #5).

``transition`` checks the table of #5.2 under the row lock, writes the
``ApplicationTransition``, bumps ``version`` and sends
``application_status_changed`` on commit. Every service calls it; nothing else
writes ``status``.
"""

import logging
from functools import partial

from django.db import transaction
from django.utils import timezone

from apps.api.errors import BusinessError

from .. import errors, signals
from ..enums import Action, ApplicationStatus
from ..models import Application, ApplicationTransition

logger = logging.getLogger(__name__)

S = ApplicationStatus

# Action -> statuses it may be taken from (#5.2). The destination is the
# caller's: some actions have more than one (sign, onboard).
TRANSITIONS = {
    Action.EDIT: (S.DRAFT,),
    Action.PROCEED_TO_SIGN: (S.DRAFT,),
    Action.DELETE: (S.DRAFT, S.PENDING_SIGNATURE, S.PENDING_PAYMENT),
    Action.BACK_TO_DRAFT: (S.PENDING_SIGNATURE,),
    Action.SIGN: (S.PENDING_SIGNATURE,),
    Action.PAY: (S.PENDING_PAYMENT,),
    Action.SUBMIT: (S.PENDING_SIGNATURE, S.PENDING_PAYMENT),
    Action.ONBOARD: (S.PENDING_REVIEW,),
    Action.DEFER_REVIEW: (S.PENDING_REVIEW,),
    Action.DISMISS: (S.PENDING_REVIEW,),
    Action.MOVE_DECISION_DATE: (S.PENDING_DECISION,),
    Action.ACCEPT: (S.PENDING_DECISION,),
    Action.REJECT: (S.PENDING_DECISION,),
    Action.EXPIRE: (S.PENDING_REVIEW, S.PENDING_DECISION),
    Action.WORKFLOW_DONE: (S.ACCEPTED, S.REJECTED),
    Action.WORKFLOW_FAILED: (S.ACCEPTED, S.REJECTED),
}

# Filer actions shown as ``allowed_actions`` / list ``actions`` (#14.1).
FILER_ACTIONS = {
    Action.EDIT: "continue",
    Action.PROCEED_TO_SIGN: "proceed_to_sign",
    Action.BACK_TO_DRAFT: "back_to_draft",
    Action.SIGN: "sign",
    Action.PAY: "pay",
    Action.DELETE: "discard",
}


# How each action reads in a message: "A draft application cannot be <done>."
ACTION_DONE = {
    Action.EDIT: "edited",
    Action.PROCEED_TO_SIGN: "sent for signature",
    Action.DELETE: "deleted",
    Action.BACK_TO_DRAFT: "moved back to draft",
    Action.SIGN: "signed",
    Action.PAY: "paid for",
    Action.SUBMIT: "submitted",
}


def allowed_actions(application):
    """Filer actions the status allows, in the order the screen shows them; roles not applied."""
    return [
        name for action, name in FILER_ACTIONS.items() if application.status in TRANSITIONS[action]
    ]


class TransitionError(BusinessError):
    """``409 E13001``, carrying the application's ``allowed_actions`` (#5.3)."""

    def __init__(self, application, action):
        self.allowed_actions = allowed_actions(application)
        status = application.get_status_display().lower()
        message = f"An application that is {status} cannot be {ACTION_DONE.get(action, 'changed')}."
        super().__init__(errors.ACTION_NOT_ALLOWED, message)


def require(application, action):
    """Raise ``E13001`` unless ``action`` may be taken from the application's status."""
    if application.status not in TRANSITIONS[action]:
        raise TransitionError(application, action)


def lock(application_id):
    """The application, row locked and re-read (#5.3)."""
    return (
        Application.objects.select_for_update(of=("self",))
        .select_related("application_type", "case", "case__court")
        .get(pk=application_id)
    )


def require_version(application, version):
    """``412 E13026`` when ``If-Match`` is given and stale (#5.3, #16.8)."""
    if version is not None and int(version) != application.version:
        raise BusinessError(errors.APPLICATION_STALE)


def log(
    application, action, actor, *, from_status, to_status, order_id=None, summary="", metadata=None
):
    """Append one transition row."""
    return ApplicationTransition.objects.create(
        application=application,
        application_ref=application.pk,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor=actor if getattr(actor, "pk", None) else None,
        order_id=order_id,
        summary=summary[:255],
        metadata=metadata or {},
    )


def save(application, actor, *fields):
    """Save with ``version + 1`` and who did it."""
    application.version += 1
    if getattr(actor, "pk", None):
        application.updated_by = actor
        application._history_user = actor
    if fields:
        application.save(update_fields=[*fields, "version", "updated_by", "updated_at"])
    else:
        application.save()


def transition(
    application,
    action,
    actor,
    *,
    to_status=None,
    order_id=None,
    summary="",
    metadata=None,
    check=True,
):
    """Move ``application`` (already locked) and log it; returns the transition row.

    ``to_status`` defaults to the current status (an action with no status
    change: edit, defer, move date, workflow attempts).
    """
    if check:
        require(application, action)
    from_status = application.status
    to_status = to_status or from_status
    application.status = to_status
    save(application, actor)
    row = log(
        application,
        action,
        actor,
        from_status=from_status,
        to_status=to_status,
        order_id=order_id,
        summary=summary,
        metadata=metadata,
    )
    if from_status != to_status:
        logger.info(
            "event=APPLICATION_STATUS_CHANGED application_id=%s from_status=%s to_status=%s "
            "action=%s order_id=%s",
            application.pk,
            from_status,
            to_status,
            action,
            order_id or "",
        )
        send_on_commit(
            signals.application_status_changed,
            application_id=application.pk,
            case_id=application.case_id,
            from_status=from_status,
            to_status=to_status,
            action=str(action),
        )
    return row


def send_on_commit(signal, **kwargs):
    """Send ``signal`` once the transaction commits; a failing receiver is logged."""
    transaction.on_commit(partial(_send, signal, kwargs))


def _send(signal, kwargs):
    for receiver, result in signal.send_robust(sender=Application, **kwargs):
        if isinstance(result, Exception):
            logger.error(
                "event=APPLICATION_SIGNAL_RECEIVER_FAILED application_id=%s receiver=%s error=%s",
                kwargs.get("application_id"),
                getattr(receiver, "__qualname__", receiver),
                result,
            )


def now():
    return timezone.now()
