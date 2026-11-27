"""The one way a process's status changes (spec 0028 #4).

Each change runs under the process's row lock, sets ``status`` and
``status_at``, appends one ``ProcessEvent`` and, on commit, sends
``process_status_changed``. A step through several statuses in one action
calls ``move`` once per status with the same time (``SGN-04``, ``DSP-10``).
"""

import logging

from django.db import transaction
from django.utils import timezone

from ..enums import EventSource
from ..models import Process, ProcessEvent
from ..signals import process_status_changed

logger = logging.getLogger(__name__)


def locked(process_id):
    """Return the process locked for update, with what the step rules read. Call inside atomic."""
    return (
        Process.objects.select_for_update(of=("self",))
        .select_related("round", "process_type", "channel")
        .get(pk=process_id)
    )


def move(process, to_status, *, source, actor=None, at=None, fields=(), **data):
    """Set the process's status, save it with ``fields``, and record the event.

    ``data`` is the event's non-sensitive detail, e.g. ``reason="REFUSED"``.
    """
    from_status = process.status
    at = at or timezone.now()
    process.status, process.status_at = to_status, at
    process.save(update_fields=["status", "status_at", "updated_at", *fields])
    record(process, from_status, source=source, actor=actor, at=at, **data)
    return process


def record(process, from_status, *, source, actor=None, at, **data):
    """Append the event for the process's change to its current status, and announce it."""
    ProcessEvent.objects.create(
        process=process,
        from_status=from_status,
        to_status=process.status,
        source=source,
        actor=actor,
        at=at,
        data=data,
    )
    payload = {
        "process_id": process.pk,
        "case_id": process.case_id,
        "from_status": from_status,
        "to_status": process.status,
    }
    logger.info(
        "event=PROCESS_STATUS_CHANGED process_id=%s from_status=%s to_status=%s source=%s",
        process.pk,
        from_status or "-",
        process.status,
        source,
    )
    transaction.on_commit(lambda: _announce(payload))


def _announce(payload):
    for receiver, result in process_status_changed.send_robust(sender=Process, **payload):
        if isinstance(result, Exception):
            logger.error(
                "event=PROCESS_SIGNAL_RECEIVER_FAILED process_id=%s receiver=%s error=%s",
                payload["process_id"],
                getattr(receiver, "__qualname__", receiver),
                result,
            )


def created(process, actor=None):
    """Record a new process's first status, set by the fan-out."""
    record(process, "", source=EventSource.SYSTEM, actor=actor, at=process.status_at)
