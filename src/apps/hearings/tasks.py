"""Hearings background jobs (spec 0023 #11.4).

Thin actors over the services: they take identifiers only, are idempotent,
and leave logging to the services. Schedules are in UTC and run by the
``scheduler`` service (spec 0026 #7.1).
"""

from dramatiq import actor
from dramatiq_crontab import cron

from .services import courtroom, reschedule


@actor(max_retries=3)
def run_bulk_reschedule(job_id: str) -> None:
    """Run a confirmed bulk move; a redelivery finishes the job instead of repeating it (#8.3)."""
    reschedule.run_bulk(job_id)


@cron("*/5 * * * *")  # every 5 minutes
@actor(max_retries=0)
def expire_bulk_previews() -> int:
    """Mark bulk previews past their expiry ``EXPIRED``."""
    return reschedule.expire_previews()


@cron("30 18 * * *")  # daily, 00:00 IST
@actor(max_retries=0)
def end_hearing_days() -> int:
    """Abandon every listing not finished on its day, for every court (``HRG-05``)."""
    return courtroom.end_days()
