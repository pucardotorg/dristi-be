"""Retry, expiry, reconciliation and cleanup (spec 0015 #9).

A retry never mutates the attempt it came from: each ESP attempt has its own
correlation id and audit trail, so a new row is created with ``retry_of`` set
and the prepared document reused. The prepared PDF is only re-created when it
has gone, which keeps the hash the ESP signs identical to the one we stored.
"""

from django.db import transaction as db_transaction
from django.utils import timezone

from .. import conf, permissions
from ..clients import get_file_client
from ..constants import (
    EVENT_ESIGN_EXPIRED,
    EVENT_ESIGN_FAILED,
    EVENT_ESIGN_RETRIED,
    TERMINAL_STATUSES,
    ESignStatus,
)
from ..exceptions import (
    ESignDisabled,
    ESignError,
    ESignMaxAttemptsExceeded,
    ESignNotRetryable,
    ESignPlaceholderMissing,
    ESignSigningInterrupted,
    ESignSourceNotFound,
)
from ..log import log_event
from ..models import ESignTransaction
from ..providers import get_provider
from .initiation import (
    InitiationResult,
    build_provider_request,
    prepare_document,
    store_placeholder,
)


def retry_transaction(parent: ESignTransaction, *, user=None) -> InitiationResult:
    """Create a fresh attempt from a ``FAILURE``/``EXPIRED`` transaction."""

    if not conf.is_enabled():
        raise ESignDisabled()
    if not parent.is_retryable:
        raise ESignNotRetryable()

    attempt_count = parent.attempt_count + 1
    if attempt_count > conf.max_attempts():
        raise ESignMaxAttemptsExceeded()

    provider = get_provider()
    actor = user if user is not None else parent.signer

    permissions.check_can_sign(
        user=actor,
        entity_type=parent.entity_type,
        entity_id=parent.entity_id,
        organization_id=parent.organization_id,
    )

    placeholder_file_id = parent.placeholder_file_id
    document_hash = parent.document_hash
    field_name = parent.signature_field_name

    if not _placeholder_available(placeholder_file_id):
        placeholder_file_id, document_hash, field_name = _reprepare(parent, actor)

    transaction = ESignTransaction.objects.create(
        organization_id=parent.organization_id,
        module=parent.module,
        entity_type=parent.entity_type,
        entity_id=parent.entity_id,
        signer=parent.signer,
        provider=provider.name,
        source_file_id=parent.source_file_id,
        placeholder_file_id=placeholder_file_id,
        sign_placeholder=parent.sign_placeholder,
        document_hash=document_hash,
        signature_field_name=field_name,
        status=ESignStatus.PENDING.value,
        attempt_count=attempt_count,
        retry_of=parent,
        expires_at=timezone.now() + conf.transaction_ttl(),
        created_by=parent.created_by,
        updated_by=parent.updated_by,
    )

    initiation = build_provider_request(transaction, provider=provider)
    log_event(
        EVENT_ESIGN_RETRIED,
        transaction,
        retry_of=str(parent.pk),
        attempt_count=attempt_count,
    )
    return InitiationResult(transaction=transaction, initiation=initiation)


def expire_stale_transactions(now=None) -> int:
    """Move ``PENDING`` rows past their TTL plus grace to ``EXPIRED``."""

    now = now or timezone.now()
    cutoff = now - conf.callback_grace_period()
    expired = 0
    for transaction in ESignTransaction.objects.filter(
        status=ESignStatus.PENDING.value,
        expires_at__lt=cutoff,
    ).iterator():
        with db_transaction.atomic():
            locked = _lock(transaction.pk)
            if locked is None or locked.status != ESignStatus.PENDING.value:
                continue
            # No failure code: EXPIRED already names the outcome, and nothing
            # failed — the user simply never came back from the ESP.
            locked.mark_expired(message="No signing response was received in time.")
            expired += 1
            log_event(EVENT_ESIGN_EXPIRED, locked)
    return expired


def reconcile_signing_transactions(now=None) -> int:
    """Fail rows stuck in ``SIGNING`` so the retry path can resolve them."""

    now = now or timezone.now()
    cutoff = now - conf.signing_stuck_timeout()
    reconciled = 0
    for transaction in ESignTransaction.objects.filter(
        status=ESignStatus.SIGNING.value,
        updated_at__lt=cutoff,
    ).iterator():
        with db_transaction.atomic():
            locked = _lock(transaction.pk)
            if locked is None or locked.status != ESignStatus.SIGNING.value:
                continue
            error = ESignSigningInterrupted()
            locked.mark_failed(error.code, error.message)
            reconciled += 1
            log_event(EVENT_ESIGN_FAILED, locked, failure_code=error.code)
    return reconciled


def cleanup_placeholders(now=None) -> int:
    """Delete placeholder PDFs of old terminal transactions and clear the id.

    Source and signed files are never touched: only the intermediate prepared
    document this module created is cleaned up.
    """

    now = now or timezone.now()
    cutoff = now - conf.placeholder_retention()
    files = get_file_client()
    removed = 0
    for transaction in (
        ESignTransaction.objects.filter(status__in=TERMINAL_STATUSES, updated_at__lt=cutoff)
        .exclude(placeholder_file_id="")
        .iterator()
    ):
        try:
            files.delete(transaction.placeholder_file_id)
        except ESignSourceNotFound:
            # Already gone; the id must still be forgotten.
            pass
        except ESignError:
            # Storage trouble: leave the id in place for the next run rather
            # than forgetting a file that still exists.
            continue
        ESignTransaction.objects.filter(pk=transaction.pk).update(
            placeholder_file_id="", updated_at=timezone.now()
        )
        removed += 1
    return removed


def _reprepare(parent: ESignTransaction, actor):
    """Re-prepare the source document when the placeholder has gone."""

    if not parent.source_file_id:
        raise ESignPlaceholderMissing()
    try:
        prepared = prepare_document(
            file_id=parent.source_file_id,
            sign_placeholder=parent.sign_placeholder,
        )
    except ESignSourceNotFound as exc:
        # Both the prepared document and the source are gone, so this document
        # cannot be signed again from here; the caller must start afresh.
        raise ESignPlaceholderMissing() from exc
    placeholder_file_id = store_placeholder(
        prepared.prepared_document,
        file_id=parent.source_file_id,
        user=actor,
        module=parent.module,
        entity_id=parent.entity_id,
        organization_id=parent.organization_id,
    )
    return placeholder_file_id, prepared.document_hash, prepared.field_name


def _placeholder_available(file_id: str) -> bool:
    """Whether the prepared document is still in storage."""

    if not file_id:
        return False
    try:
        get_file_client().get_metadata(file_id)
    except ESignError:
        return False
    return True


def _lock(pk):
    """Re-read a row under ``select_for_update`` so a sweep cannot race a callback."""

    return ESignTransaction.objects.select_for_update().filter(pk=pk).first()
