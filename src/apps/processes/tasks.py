"""Processes background jobs (spec 0028 #12.5).

Thin actors over the services, idempotent; schedules are in UTC (spec 0026).
"""

from dramatiq import actor
from dramatiq_crontab import cron

from .services import expiry


@cron("*/5 * * * *")  # every 5 minutes
@actor(max_retries=0)
def expire_processes() -> int:
    """Expire unsent processes past their expiry (``EXP-02``)."""
    return expiry.expire_due()
