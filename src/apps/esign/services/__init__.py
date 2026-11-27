"""Domain services for the signing lifecycle (spec 0015 #2, #8, #9; spec 0038 #8)."""

from .callback import CallbackOutcome, process_callback
from .client_signature import CompletionOutcome, complete_with_client_signature
from .initiation import InitiationResult, initiate_esign
from .recovery import (
    cleanup_placeholders,
    expire_stale_transactions,
    reconcile_signing_transactions,
    retry_transaction,
)

__all__ = [
    "CallbackOutcome",
    "CompletionOutcome",
    "InitiationResult",
    "cleanup_placeholders",
    "complete_with_client_signature",
    "expire_stale_transactions",
    "initiate_esign",
    "process_callback",
    "reconcile_signing_transactions",
    "retry_transaction",
]
