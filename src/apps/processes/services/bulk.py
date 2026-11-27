"""Taking a step on one process or on several at once (spec 0028 #4, ``SGN-03``, ``PIA-01``).

Every step runs the same way: under the process's lock, the step's action
and conditions checked (``steps.check``), then the change. On one process a
step that does not apply is refused (``409``). On several, the screens act
on a selection, so:

* access is all or nothing: one process the caller may not take the step on
  refuses the request (``403 E12015``) and nothing changes;
* a process the step does not apply to now (it moved on meanwhile) is
  skipped and returned with its status;
* the processes are locked in one order, so two requests over overlapping
  selections cannot deadlock.
"""

from django.db import transaction

from apps.api.errors import BusinessError

from .. import conf, errors, steps
from . import transitions


def check_size(process_ids, field="process_ids"):
    """Refuse more processes in one request than ``processes.bulk_max``."""
    if len(process_ids) > conf.bulk_max():
        raise BusinessError(errors.BULK_TOO_LARGE, field=field)


def one(process_id, actor, step, apply):
    """Take ``step`` on one process: ``apply(process)`` once it is locked and checked."""
    with transaction.atomic():
        process = transitions.locked(process_id)
        steps.check(actor, process, step)
        return apply(process)


def each(process_ids, actor, step, apply):
    """Take ``step`` on several processes; return ``(done, skipped)``.

    ``apply(process)`` makes the change. A ``BusinessError`` it raises, or a
    refused action, rolls back every process.
    """
    check_size(process_ids)
    done, skipped = [], []
    with transaction.atomic():
        for process_id in sorted(set(process_ids)):
            process = transitions.locked(process_id)
            try:
                steps.check(actor, process, step)
            except steps.StepNotApplicable:
                skipped.append(process)
                continue
            apply(process)
            done.append(process)
    return done, skipped


def within(path, error: BusinessError):
    """Return ``error`` with its field moved under ``path``, e.g. ``outcomes[2].reason``."""
    detail = error.detail
    if isinstance(detail, dict):
        field, messages = next(iter(detail.items()))
        return BusinessError(error.error, str(messages[0]), field=f"{path}.{field}")
    return BusinessError(error.error, str(detail), field=path)
