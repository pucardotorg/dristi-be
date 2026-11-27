"""The type's workflow after the decision (spec 0033 #12).

On acceptance the type's workflow runs, always (``ALC-16``); rejection runs
``on_reject`` only where the type needs it (Delay Condonation). A failure never
undoes the decision — the signed order is the court's — it leaves
``workflow_status = FAILED``, records the attempt and is retried by the
``run_type_workflow`` actor, then by the admin action.
"""

import logging

from django.db import transaction

from ..enums import ApplicationStatus, WorkflowStatus
from . import common
from .common import Action

logger = logging.getLogger(__name__)

S = ApplicationStatus
RUNNABLE = (WorkflowStatus.PENDING, WorkflowStatus.FAILED)


def enqueue(application_id):
    """Run the workflow once the deciding transaction commits."""
    from ..tasks import run_type_workflow

    transaction.on_commit(lambda: run_type_workflow.send(str(application_id)))


def attempts(application):
    return application.transitions.filter(
        action__in=(Action.WORKFLOW_DONE, Action.WORKFLOW_FAILED)
    ).count()


def run(application_id):
    """One attempt; a no-op unless ``workflow_status`` is ``PENDING`` or ``FAILED``.

    Returns ``(workflow_status, attempts so far)``.
    """
    with transaction.atomic():
        application = common.lock(application_id)
        if application.workflow_status not in RUNNABLE:
            return application.workflow_status, attempts(application)
        attempt = attempts(application) + 1
        spec = application.spec
        try:
            with transaction.atomic():
                if application.status == S.ACCEPTED:
                    result = spec.on_accept(
                        application, order_id=application.deciding_order_id, values={}
                    )
                else:
                    spec.on_reject(application, order_id=application.deciding_order_id)
                    result = {}
        except Exception as exc:  # noqa: BLE001 - every failure is recorded, never raised
            error_code = getattr(exc, "code", None) or type(exc).__name__
            application.workflow_status = WorkflowStatus.FAILED
            common.transition(
                application,
                Action.WORKFLOW_FAILED,
                None,
                metadata={"error_code": str(error_code), "attempt": attempt},
            )
            logger.error(
                "event=APPLICATION_WORKFLOW_FAILED application_id=%s error_code=%s attempt=%s",
                application.pk,
                error_code,
                attempt,
            )
            return application.workflow_status, attempt
        application.workflow_status = WorkflowStatus.DONE
        common.transition(
            application,
            Action.WORKFLOW_DONE,
            None,
            summary=str((result or {}).get("summary", ""))[:255],
            metadata={"result": _jsonable(result or {}), "attempt": attempt},
        )
        return application.workflow_status, attempt


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
