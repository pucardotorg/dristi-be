"""Background jobs (spec 0033 #16.6). Ids only, idempotent, enqueued on commit."""

from dramatiq import actor
from dramatiq_crontab import cron

from . import conf
from .enums import WorkflowStatus
from .services import expiry, objections, workflows

# Backoff between attempts of a failing type workflow, per attempt so far.
WORKFLOW_BACKOFF_MS = 60_000


@actor(max_retries=0)
def run_type_workflow(application_id: str) -> str:
    """One attempt at the type's workflow (#12.1).

    A failure is recorded by ``workflows.run``, never raised; this actor
    re-enqueues itself with a growing delay until ``workflow_max_retries``
    attempts have failed. After that the admin action retries it.
    """
    status, attempt = workflows.run(application_id)
    if status == WorkflowStatus.FAILED and attempt < conf.workflow_max_retries():
        run_type_workflow.send_with_options(
            args=(application_id,), delay=WORKFLOW_BACKOFF_MS * attempt
        )
    return status


@cron("35 18 * * *")  # daily, 00:05 IST
@actor(max_retries=0)
def expire_hearing_linked_applications() -> int:
    """Expire Advance / Postpone applications whose hearing passed and no signal caught (#13)."""
    return expiry.sweep()


@cron("35 18 * * *")  # daily, 00:05 IST
@actor(max_retries=0)
def close_objection_windows() -> int:
    """Expire *File objection* windows whose respond-by date has passed (#9)."""
    return objections.close_windows()
