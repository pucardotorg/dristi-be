"""The party's steps: the fee and the envelope (spec 0028 #6.3, #7.1).

A process waits in ``PENDING_STEPS`` until both that apply are done, in
either order; then it waits for signing (``STP-03``, ``FEE-08``). Other
processes of the round never wait on it.
"""

import logging

from django.db import transaction
from django.utils import timezone

from .. import steps
from ..enums import EventSource, ProcessStatus, Step
from ..models import Process
from . import transitions

logger = logging.getLogger(__name__)


def initial_status(process):
    """``PENDING_SIGNATURE`` when nothing is outstanding, else ``PENDING_STEPS``."""
    return ProcessStatus.PENDING_SIGNATURE if process.steps_done else ProcessStatus.PENDING_STEPS


def _save_step(process, fields, *, source, actor, at):
    """Save a step done; move on to signing if it was the last one outstanding."""
    if process.status == ProcessStatus.PENDING_STEPS and process.steps_done:
        transitions.move(
            process,
            ProcessStatus.PENDING_SIGNATURE,
            source=source,
            actor=actor,
            at=at,
            fields=fields,
        )
    else:
        process.save(update_fields=[*fields, "updated_at"])
    return process


def receive_envelope(*, process_id, actor):
    """Record receipt of the process's envelope at the counter (``STP-02``)."""
    with transaction.atomic():
        process = transitions.locked(process_id)
        steps.check(actor, process, Step.RECEIVE_ENVELOPE)
        now = timezone.now()
        process.envelope_received_by, process.envelope_received_at = actor, now
        return _save_step(
            process,
            ["envelope_received_by", "envelope_received_at"],
            source=EventSource.USER,
            actor=actor,
            at=now,
        )


def fee_items_paid(item_ids):
    """Mark the processes whose demand items are now paid; idempotent (#6.3).

    Called for a successful payment only, so a ``PENDING`` one never moves a
    process. Returns how many were marked.
    """
    ids = list(
        Process.objects.filter(demand_item_id__in=list(item_ids), fee_paid=False).values_list(
            "pk", flat=True
        )
    )
    marked = 0
    for process_id in ids:
        with transaction.atomic():
            process = transitions.locked(process_id)
            if process.fee_paid:
                continue
            now = timezone.now()
            process.fee_paid, process.fee_paid_at = True, now
            _save_step(
                process, ["fee_paid", "fee_paid_at"], source=EventSource.SYSTEM, actor=None, at=now
            )
            marked += 1
    if marked:
        logger.info("event=PROCESS_FEES_PAID count=%s", marked)
    return marked
