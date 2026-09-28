"""Structured logging for the signing lifecycle (spec 0015 #13).

One line per stage, always carrying the correlation fields, and never the
document bytes, the PKCS#7 blob, the raw callback body or key material.
"""

import logging

logger = logging.getLogger("apps.esign")


def _context(transaction) -> dict:
    """Return the standard correlation fields for a transaction."""

    if transaction is None:
        return {}
    return {
        "transaction_id": str(transaction.pk),
        "provider_transaction_id": transaction.provider_transaction_id,
        "organization_id": str(transaction.organization_id) if transaction.organization_id else "",
        "module": transaction.module,
        "status": transaction.status,
    }


def log_event(event: str, transaction=None, *, level: int = logging.INFO, **extra) -> None:
    """Emit one structured line for ``event``."""

    fields = {"event": event, **_context(transaction), **extra}
    logger.log(level, " ".join(f"{key}={value!r}" for key, value in fields.items()))
