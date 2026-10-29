"""Periodic maintenance actors (spec 0015 #9).

Only maintenance is asynchronous: the signing flow itself is synchronous, and
these actors exist so abandoned, interrupted and stale artefacts do not
accumulate. Each is idempotent — running it twice changes nothing extra.

Schedules are in UTC and run by the ``scheduler`` service (spec 0026 #7.1).
"""

from dramatiq import actor
from dramatiq_crontab import cron

from .services import recovery


@cron("*/5 * * * *")  # every 5 minutes
@actor(max_retries=0)
def expire_stale_transactions() -> int:
    """Move ``PENDING`` transactions past their TTL plus grace to ``EXPIRED``."""

    return recovery.expire_stale_transactions()


@cron("*/5 * * * *")  # every 5 minutes
@actor(max_retries=0)
def reconcile_signing_transactions() -> int:
    """Fail transactions left in ``SIGNING`` by an interrupted worker."""

    return recovery.reconcile_signing_transactions()


@cron("30 20 * * *")  # daily, 02:00 IST
@actor(max_retries=0)
def cleanup_placeholders() -> int:
    """Delete placeholder PDFs of terminal transactions past their retention."""

    return recovery.cleanup_placeholders()
