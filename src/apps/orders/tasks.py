"""Orders background jobs (spec 0039 #12.7).

Thin actors over the services: they take identifiers only and are idempotent.
"""

from dramatiq import actor

from .services import triggering

RETRY_BACKOFF_MS = 30_000


@actor(max_retries=3)
def run_order_workflows(order_id: str) -> None:
    """Run a triggered order's workflow steps; a redelivery finishes rather than repeats (#9.2).

    While steps remain retryable, schedules itself again with growing backoff.
    """
    remaining = triggering.run(order_id)
    if remaining:
        from .models import OrderWorkflowRun

        attempts = (
            OrderWorkflowRun.objects.filter(order_id=order_id)
            .order_by("-attempts")
            .values_list("attempts", flat=True)
            .first()
        ) or 1
        run_order_workflows.send_with_options(
            args=(order_id,), delay=RETRY_BACKOFF_MS * 2 ** (attempts - 1)
        )
