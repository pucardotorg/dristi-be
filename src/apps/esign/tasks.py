"""Periodic maintenance actors (spec 0015 #9).

Only maintenance is asynchronous: the signing flow itself is synchronous, and
these actors exist so abandoned, interrupted and stale artefacts do not
accumulate. Each is idempotent — running it twice changes nothing extra.
"""

from dramatiq import actor

from .services import recovery


@actor(max_retries=0)
def expire_stale_transactions() -> int:
    """Move ``PENDING`` transactions past their TTL plus grace to ``EXPIRED``."""

    return recovery.expire_stale_transactions()


@actor(max_retries=0)
def reconcile_signing_transactions() -> int:
    """Fail transactions left in ``SIGNING`` by an interrupted worker."""

    return recovery.reconcile_signing_transactions()


@actor(max_retries=0)
def cleanup_placeholders() -> int:
    """Delete placeholder PDFs of terminal transactions past their retention."""

    return recovery.cleanup_placeholders()
