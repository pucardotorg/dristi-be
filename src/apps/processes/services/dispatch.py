"""Send, outcome and recall (spec 0028 #8.1, #8.2, #8.4).

Only the people's steps are here: marking a manual channel's process sent,
recording a manual outcome, and recalling. A system send, its resend, polling
and callbacks go through the channel backends, which come with that work.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.payments.selectors import unpaid_item
from apps.payments.services import DemandService

from .. import conf, errors, steps
from ..enums import EventSource, ProcessStatus, Step
from ..models import NonDeliveryReason
from . import transitions

logger = logging.getLogger(__name__)

PROCLAMATION = "PROCLAMATION"
BY_HAND = "BY_HAND"


def _is_publication(process):
    return process.process_type.code == PROCLAMATION and process.channel.code == BY_HAND


def send(*, process_id, actor, published=False):
    """Mark a signed process sent once it has left in that form (``DSP-03``).

    ``published`` records a by-hand proclamation sent and executed at once:
    published, so there is no outcome to wait for (``DSP-10``).
    """
    with transaction.atomic():
        process = transitions.locked(process_id)
        steps.check(actor, process, Step.SEND)
        if published and not _is_publication(process):
            raise BusinessError(
                errors.INVALID_PROCESS_ACTION,
                "Only a proclamation by hand is marked as published.",
                field="published",
            )
        now = timezone.now()
        process.sent_by, process.sent_at = actor, now
        transitions.move(
            process,
            ProcessStatus.SENT,
            source=EventSource.USER,
            actor=actor,
            at=now,
            fields=("sent_by", "sent_at"),
        )
        if published:
            process.outcome_date = conf.court_date(now)
            transitions.move(
                process,
                ProcessStatus.DELIVERED,
                source=EventSource.USER,
                actor=actor,
                at=now,
                fields=("outcome_date",),
                published=True,
            )
        return process


def record_outcome(
    *, process_id, actor, status, reason="", outcome_date=None, comment="", file_id=""
):
    """Record what became of a sent process on a manual status channel (``DSP-08``, ``DSP-09``)."""
    with transaction.atomic():
        process = transitions.locked(process_id)
        steps.check(actor, process, Step.RECORD_OUTCOME)
        today = conf.court_date()
        outcome_date = outcome_date or today
        if not conf.court_date(process.sent_at) <= outcome_date <= today:
            raise BusinessError(errors.OUTCOME_DATE_INVALID, field="outcome_date")
        process.reason = _reason(reason) if status == ProcessStatus.NOT_DELIVERED else None
        process.outcome_date, process.remark, process.outcome_file_id = (
            outcome_date,
            comment,
            file_id,
        )
        return transitions.move(
            process,
            status,
            source=EventSource.USER,
            actor=actor,
            fields=("reason", "outcome_date", "remark", "outcome_file_id"),
            reason=reason if process.reason else "",
        )


def _reason(code):
    reason = (
        NonDeliveryReason.objects.active().filter(state_code=conf.state_code(), code=code).first()
    )
    if reason is None:
        raise BusinessError(errors.REASON_REQUIRED, field="reason")
    return reason


def check_bulk_size(process_ids):
    """Refuse more processes in one request than ``processes.bulk_max``."""
    if len(process_ids) > conf.bulk_max():
        raise BusinessError(errors.BULK_TOO_LARGE, field="process_ids")


def recall(*, process_ids, actor, comment=""):
    """Recall processes with no outcome yet, sent or not (``PIA-01``).

    All or nothing on access: one process the caller may not recall refuses
    the request (``403 E12015``). A process already ended is skipped and
    returned with its status. Returns ``(recalled, skipped)``.
    """
    check_bulk_size(process_ids)
    recalled, skipped = [], []
    with transaction.atomic():
        # Locked in one order, so two recalls of overlapping lists cannot deadlock.
        for process_id in sorted(set(process_ids)):
            process = transitions.locked(process_id)
            try:
                steps.check(actor, process, Step.RECALL)
            except steps.StepNotApplicable:
                skipped.append(process)
                continue
            now = timezone.now()
            process.recalled_by, process.recalled_at, process.remark = actor, now, comment
            transitions.move(
                process,
                ProcessStatus.RECALLED,
                source=EventSource.USER,
                actor=actor,
                at=now,
                fields=("recalled_by", "recalled_at", "remark"),
            )
            _cancel_unpaid_fee(process, actor)
            recalled.append(process)
    return recalled, skipped


def _cancel_unpaid_fee(process, actor):
    """A process recalled before its fee is paid is never paid for (0017 #6.1)."""
    if process.fee_paid or process.demand_item_id is None:
        return
    item = unpaid_item(process.demand_item_id)
    if item is not None:
        DemandService.cancel_item(item, reason="Process recalled.", actor=actor)
