"""Send, outcome and recall (spec 0028 #8.1, #8.2, #8.4).

Only the people's steps are here: marking a manual channel's process sent,
recording a manual outcome, and recalling. A system send, its resend, polling
and callbacks go through the channel backends, which come with that work.
Each step is taken on one process or on a selection (``bulk``).
"""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.files.documents import store_documents
from apps.files.services import FileNotFound, get_file
from apps.payments.selectors import unpaid_item
from apps.payments.services import DemandService

from .. import conf, errors
from ..enums import EventSource, ProcessStatus, Step
from ..selectors import non_delivery_reasons
from . import bulk, transitions

logger = logging.getLogger(__name__)

# Every outcome's supporting file carries this tag and its process's id.
OUTCOME_FILE_TAG = "process-outcome"


def _send(process, actor, published=False):
    if published and not process.is_publication:
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


def send(*, process_id, actor, published=False):
    """Mark a signed process sent once it has left in that form (``DSP-03``).

    ``published`` records a by-hand proclamation sent and executed at once:
    published, so there is no outcome to wait for (``DSP-10``).
    """
    return bulk.one(process_id, actor, Step.SEND, lambda p: _send(p, actor, published))


def send_many(*, process_ids, actor):
    """Mark a selection sent: covers posted, processes handed over (``DSP-03``)."""
    return bulk.each(process_ids, actor, Step.SEND, lambda p: _send(p, actor))


def _reason(process, code):
    """The state's reason ``code``, where it is one for the process's type (``DSP-09``)."""
    reason = non_delivery_reasons(process.process_type.code).filter(code=code).first()
    if reason is None:
        raise BusinessError(errors.REASON_REQUIRED, field="reason")
    return reason


def _outcome_file_tags(process):
    return [OUTCOME_FILE_TAG, str(process.pk)]


def store_outcome_file(*, process_id, actor, upload):
    """Store a supporting file for the process's outcome; return its ``file_id`` (``DSP-08``).

    Only where recording the outcome is a step the caller may take now. The
    file is tagged with the process, so its outcome accepts it and no other.
    """
    return bulk.one(
        process_id,
        actor,
        Step.RECORD_OUTCOME,
        lambda p: store_documents([upload], user_id=actor.pk, tags=_outcome_file_tags(p))[0],
    )


def _check_file(process, file_id):
    try:
        tags = get_file(file_id)["tags"]
    except (FileNotFound, DjangoValidationError, ValueError):
        tags = []
    if not set(_outcome_file_tags(process)) <= set(tags):
        raise BusinessError(errors.OUTCOME_FILE_INVALID, field="file_id")


def _record(process, actor, *, status, reason="", outcome_date=None, comment="", file_id=""):
    today = conf.court_date()
    outcome_date = outcome_date or today
    if not conf.court_date(process.sent_at) <= outcome_date <= today:
        raise BusinessError(errors.OUTCOME_DATE_INVALID, field="outcome_date")
    if file_id:
        _check_file(process, file_id)
    process.reason = _reason(process, reason) if status == ProcessStatus.NOT_DELIVERED else None
    process.outcome_date, process.remark, process.outcome_file_id = outcome_date, comment, file_id
    return transitions.move(
        process,
        status,
        source=EventSource.USER,
        actor=actor,
        fields=("reason", "outcome_date", "remark", "outcome_file_id"),
        reason=reason if process.reason else "",
    )


def record_outcome(*, process_id, actor, **outcome):
    """Record what became of a sent process on a manual status channel (``DSP-08``, ``DSP-09``).

    ``outcome`` is ``status``, and optionally ``reason``, ``outcome_date``,
    ``comment`` and ``file_id``.
    """
    return bulk.one(process_id, actor, Step.RECORD_OUTCOME, lambda p: _record(p, actor, **outcome))


def record_outcomes(*, outcomes, actor, outcome_date=None):
    """Record a pile of returns, each with its own outcome; return ``(done, skipped)``.

    ``outcomes`` is ``[{"process_id", "status", ...}]`` as for one process.
    ``outcome_date`` is the batch's date, for an item that gives none. A
    refused item refuses the batch, with its field under ``outcomes[i]``.
    """
    at = {each["process_id"]: (index, each) for index, each in enumerate(outcomes)}

    def apply(process):
        index, item = at[process.pk]
        fields = {key: value for key, value in item.items() if key != "process_id"}
        fields["outcome_date"] = fields.get("outcome_date") or outcome_date
        try:
            return _record(process, actor, **fields)
        except BusinessError as error:
            raise bulk.within(f"outcomes[{index}]", error) from error

    return bulk.each(list(at), actor, Step.RECORD_OUTCOME, apply)


def _recall(process, actor, comment):
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
    return process


def recall(*, process_ids, actor, comment=""):
    """Recall processes with no outcome yet, sent or not; return ``(done, skipped)`` (``PIA-01``).

    A process already ended is skipped and returned with its status.
    """
    return bulk.each(process_ids, actor, Step.RECALL, lambda p: _recall(p, actor, comment))


def _cancel_unpaid_fee(process, actor):
    """A process recalled before its fee is paid is never paid for (0017 #6.1)."""
    if process.fee_paid or process.demand_item_id is None:
        return
    item = unpaid_item(process.demand_item_id)
    if item is not None:
        DemandService.cancel_item(item, reason="Process recalled.", actor=actor)
