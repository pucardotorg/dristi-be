"""Authenticated client-signature completion (spec 0038 #6.3, #8).

Provider-agnostic: the signer's own client posts a detached PKCS#7, which the
provider verifies against the prepared document (``verify_client_signature``)
before the shared embed/store/finalize path runs. Only ``CLIENT_SIGNATURE``
providers may complete here, so the anonymous callback and this endpoint stay
strictly separated by capability (never by name).
"""

import base64
import binascii
from dataclasses import dataclass

from django.db import transaction as db_transaction

from ..constants import (
    EVENT_CLIENT_SIGNATURE_VERIFIED,
    EVENT_ESIGN_EXPIRED,
    EVENT_ESIGN_FAILED,
    ESignStatus,
)
from ..exceptions import (
    ESignAlreadyInProgress,
    ESignClientSignatureInvalid,
    ESignClientSignatureMissing,
    ESignError,
    ESignNotProcessable,
    ESignResponseStale,
    ESignTransactionNotFound,
)
from ..log import log_event
from ..models import ESignTransaction
from ..providers import Completion, registry
from .callback import finalize_signature
from .initiation import safe_audit


@dataclass(frozen=True)
class CompletionOutcome:
    """The result returned to the authenticated caller."""

    transaction: ESignTransaction
    status: str


def complete_with_client_signature(
    transaction: ESignTransaction, pkcs7_b64: str
) -> CompletionOutcome:
    """Verify, embed and store a client-supplied signature for ``transaction``."""

    provider = registry.get(transaction.provider)
    if Completion.CLIENT_SIGNATURE not in provider.completion:
        # A CALLBACK transaction cannot be completed through this endpoint.
        raise ESignNotProcessable(audit={"provider": transaction.provider})

    pkcs7 = _decode(pkcs7_b64)

    gated, proceed, expired = _gate(transaction.pk)
    if expired:
        _expire(gated)
        raise ESignResponseStale()
    if not proceed:
        # Already SUCCESS: return the existing outcome idempotently.
        return CompletionOutcome(transaction=gated, status=gated.status)

    response_audit = _verify(gated, provider, pkcs7)
    locked = finalize_signature(gated, pkcs7, response_audit)
    return CompletionOutcome(transaction=locked, status=locked.status)


def _decode(pkcs7_b64: str) -> bytes:
    """Return the PKCS#7 bytes from base64, or raise a client error."""

    if not pkcs7_b64 or not pkcs7_b64.strip():
        raise ESignClientSignatureMissing()
    try:
        pkcs7 = base64.b64decode("".join(pkcs7_b64.split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ESignClientSignatureInvalid() from exc
    if not pkcs7:
        raise ESignClientSignatureInvalid()
    return pkcs7


def _gate(pk):
    """Lock the row and apply the state gate, marking it ``SIGNING`` to proceed.

    Returns ``(transaction, proceed, expired)``. ``proceed`` is False only for an
    already-``SUCCESS`` row (answered idempotently). A concurrent ``SIGNING``
    row, or a terminal failure, is refused.
    """

    with db_transaction.atomic():
        transaction = ESignTransaction.objects.select_for_update().filter(pk=pk).first()
        if transaction is None:
            raise ESignTransactionNotFound()
        if transaction.status == ESignStatus.SUCCESS.value:
            return transaction, False, False
        if transaction.status == ESignStatus.SIGNING.value:
            raise ESignAlreadyInProgress()
        if transaction.status in (ESignStatus.FAILURE.value, ESignStatus.EXPIRED.value):
            raise ESignNotProcessable(audit={"status": transaction.status})
        if not transaction.is_callback_window_open():
            return transaction, False, True
        transaction.mark_signing()
        return transaction, True, False


def _verify(transaction: ESignTransaction, provider, pkcs7: bytes) -> dict:
    """Run the provider's client-signature verification, recording a failure.

    On success returns the persistable, redacted response audit (certificate
    metadata only). On failure the transaction is moved to ``FAILURE`` and the
    error re-raised, so the row never stays stuck in ``SIGNING``.
    """

    try:
        response = provider.verify_client_signature(transaction, pkcs7)
    except ESignError as exc:
        transaction.mark_failed(exc.code, exc.message, response_audit=safe_audit(exc.audit))
        log_event(EVENT_ESIGN_FAILED, transaction, failure_code=exc.code)
        exc.transaction = transaction
        raise

    response_audit = safe_audit(dict(response.response_audit or {}))
    # ``response_audit`` already carries ``provider``; splat only the scalar
    # metadata so the log line records the certificate details.
    log_event(
        EVENT_CLIENT_SIGNATURE_VERIFIED,
        transaction,
        **{k: v for k, v in response_audit.items() if isinstance(v, str | int | float | bool)},
    )
    return response_audit


def _expire(transaction: ESignTransaction) -> None:
    """Close a transaction whose completion arrived after the grace period."""

    with db_transaction.atomic():
        locked = ESignTransaction.objects.select_for_update().filter(pk=transaction.pk).first()
        if locked is None or locked.status != ESignStatus.PENDING.value:
            return
        locked.mark_expired(message="The signature arrived after the transaction expired.")
    log_event(EVENT_ESIGN_EXPIRED, transaction)
