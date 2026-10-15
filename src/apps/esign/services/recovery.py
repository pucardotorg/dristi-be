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
    ACTIVE_STATUSES,
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
    reject_if_in_progress,
    store_placeholder,
)


def retry_transaction(parent: ESignTransaction, *, user=None) -> InitiationResult:
    """Create a fresh attempt from a ``FAILURE``/``EXPIRED`` transaction.

    An attempt may be retried exactly once. Without that rule the budget could
    be walked around entirely: ``attempt_count`` is derived from the parent, so
    repeatedly retrying the same dead row would mint sibling attempts that all
    claim the same number and never exhaust ``ESIGN_MAX_ATTEMPTS``. The check
    and the insert therefore happen together, under a row lock, so two
    concurrent retries cannot both pass.
    """

    if not conf.is_enabled():
        raise ESignDisabled()

    provider = get_provider()
    actor = user if user is not None else parent.signer

    permissions.check_can_sign(
        user=actor,
        entity_type=parent.entity_type,
        entity_id=parent.entity_id,
        organization_id=parent.organization_id,
    )

    transaction = _claim_retry(parent, provider=provider)

    # Re-preparing calls the PDF and File Storage services, so it happens after
    # the lock is released; the claimed row records a failure if it cannot be
    # done, exactly as any other post-creation failure does.
    if not _placeholder_available(transaction.placeholder_file_id):
        _repair_placeholder(transaction, actor)

    initiation = build_provider_request(transaction, provider=provider)
    log_event(
        EVENT_ESIGN_RETRIED,
        transaction,
        retry_of=str(parent.pk),
        attempt_count=transaction.attempt_count,
    )
    return InitiationResult(transaction=transaction, initiation=initiation)


def _claim_retry(parent: ESignTransaction, *, provider) -> ESignTransaction:
    """Validate eligibility and create the next attempt under a row lock."""

    with db_transaction.atomic():
        locked = _lock(parent.pk)
        if locked is None or not locked.is_retryable:
            raise ESignNotRetryable()
        if locked.retries.exists():
            raise ESignNotRetryable(
                "This attempt has already been retried; continue from the newer attempt."
            )
        # A fresh _esign may have started on the same document after this
        # attempt failed; a retry must not stack a second live attempt on it.
        reject_if_in_progress(
            file_id=locked.source_file_id,
            entity_type=locked.entity_type,
            entity_id=locked.entity_id,
        )

        attempt_count = locked.attempt_count + 1
        if attempt_count > conf.max_attempts():
            raise ESignMaxAttemptsExceeded()

        return ESignTransaction.objects.create(
            organization_id=locked.organization_id,
            module=locked.module,
            entity_type=locked.entity_type,
            entity_id=locked.entity_id,
            signer=locked.signer,
            provider=provider.name,
            source_file_id=locked.source_file_id,
            placeholder_file_id=locked.placeholder_file_id,
            sign_placeholder=locked.sign_placeholder,
            document_hash=locked.document_hash,
            signature_field_name=locked.signature_field_name,
            status=ESignStatus.PENDING.value,
            attempt_count=attempt_count,
            retry_of=locked,
            expires_at=timezone.now() + conf.transaction_ttl(),
            created_by=locked.created_by,
            updated_by=locked.updated_by,
        )


def _repair_placeholder(transaction: ESignTransaction, actor) -> None:
    """Re-prepare the source document for a claimed retry, or fail the row."""

    try:
        placeholder_file_id, document_hash, field_name = _reprepare(transaction, actor)
    except ESignError as exc:
        transaction.mark_failed(exc.code, exc.message)
        log_event(EVENT_ESIGN_FAILED, transaction, failure_code=exc.code)
        exc.transaction = transaction
        raise

    transaction.placeholder_file_id = placeholder_file_id
    transaction.document_hash = document_hash
    transaction.signature_field_name = field_name
    transaction.save(
        update_fields=[
            "placeholder_file_id",
            "document_hash",
            "signature_field_name",
            "updated_at",
        ]
    )


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
    document this module created is cleaned up. A placeholder is also kept while
    any live transaction still points at it — a retry reuses its parent's
    ``placeholder_file_id``, so the terminal parent and the active child share
    one file, and deleting it would break the child's callback.
    """

    now = now or timezone.now()
    cutoff = now - conf.placeholder_retention()
    files = get_file_client()
    removed = 0
    for transaction in (
        ESignTransaction.objects.filter(status__in=TERMINAL_STATUSES, updated_at__lt=cutoff)
        .exclude(placeholder_file_id="")
        .exclude(placeholder_file_id__in=_active_placeholder_ids())
        .iterator()
    ):
        file_id = transaction.placeholder_file_id
        # Re-check just before deleting: a retry may have started referencing
        # this placeholder since the iterator snapshot was taken.
        if _is_referenced_by_active(file_id):
            continue

        try:
            files.delete(file_id)
        except ESignSourceNotFound:
            # Already gone; the id must still be forgotten.
            pass
        except ESignError:
            # Storage trouble: leave the id in place for the next run rather
            # than forgetting a file that still exists.
            continue
        # Compare-and-set against what was read: the row may have moved on
        # since the iterator produced it, and clearing an id this sweep never
        # deleted would lose the only reference to a file that still exists.
        removed += ESignTransaction.objects.filter(
            pk=transaction.pk,
            status__in=TERMINAL_STATUSES,
            placeholder_file_id=file_id,
        ).update(placeholder_file_id="", updated_at=timezone.now())
    return removed


def _active_placeholder_ids():
    """Placeholder ids still referenced by a ``PENDING``/``SIGNING`` transaction."""

    return (
        ESignTransaction.objects.filter(status__in=ACTIVE_STATUSES)
        .exclude(placeholder_file_id="")
        .values_list("placeholder_file_id", flat=True)
    )


def _is_referenced_by_active(file_id: str) -> bool:
    """Whether a live transaction still points at ``file_id``."""

    return ESignTransaction.objects.filter(
        status__in=ACTIVE_STATUSES, placeholder_file_id=file_id
    ).exists()


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
