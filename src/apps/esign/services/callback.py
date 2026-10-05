"""Callback processing: verify, gate, embed, store (spec 0015 #8).

The external calls sit between two short database transactions rather than
inside one, because a network/service call cannot participate in a Postgres
transaction and must not hold a row lock. ``SIGNING`` is the durable marker that
makes the middle step recoverable, and — together with the unique
``(provider, provider_transaction_id)`` pair — guarantees at most one signed
file per transaction however many times C-DAC delivers the callback.
"""

import base64
import binascii
import logging
from collections.abc import Mapping
from dataclasses import dataclass

from django.db import transaction as db_transaction

from ..clients import get_file_client, get_pdf_client
from ..clients.pdf import prepared_document_max_bytes
from ..constants import (
    EVENT_CALLBACK_RECEIVED,
    EVENT_CALLBACK_VERIFIED,
    EVENT_ESIGN_EXPIRED,
    EVENT_ESIGN_FAILED,
    EVENT_ESIGN_SUCCEEDED,
    EVENT_SIGNATURE_EMBEDDED,
    EVENT_SIGNED_STORED,
    FILE_TYPE_SIGNED_PDF,
    SIGNED_FILENAME_SUFFIX,
    ESignStatus,
)
from ..exceptions import (
    ESignError,
    ESignFileStorageError,
    ESignNotProcessable,
    ESignPDFEmbedError,
    ESignProviderRejected,
    ESignResponseStale,
    ESignSignatureInvalid,
    ESignSignatureMissing,
    ESignSignedUploadError,
    ESignTransactionNotFound,
)
from ..log import log_event
from ..models import ESignTransaction
from ..providers import ESignProviderResponse, get_provider
from .initiation import actor_id, artefact_tags, safe_audit

# Failure codes a provider is allowed to report directly; anything else it
# sends is recorded in the audit and reported as a generic ESP rejection.
PROVIDER_FAILURE_CODES = frozenset(
    {
        ESignProviderRejected.code,
        ESignSignatureMissing.code,
        ESignSignatureInvalid.code,
    }
)


@dataclass(frozen=True)
class CallbackOutcome:
    """The result a browser is redirected with."""

    transaction: ESignTransaction
    status: str


def process_callback(payload: Mapping[str, str]) -> CallbackOutcome:
    """Process one ESP callback and return the outcome to redirect with.

    Raises an :class:`ESignError` when the callback is rejected outright —
    malformed, untrusted, stale, unknown or no longer processable — because
    nothing may be recorded for a caller we do not trust.
    """

    provider = get_provider()
    log_event(EVENT_CALLBACK_RECEIVED, None, provider=provider.name)

    parsed = provider.parse_response(payload)
    provider.verify_response(payload)
    log_event(
        EVENT_CALLBACK_VERIFIED,
        None,
        provider=provider.name,
        provider_transaction_id=parsed.provider_transaction_id,
        success=parsed.success,
    )

    transaction, proceed, expired = _gate(provider.name, parsed)
    if expired:
        # Recorded outside the gate's transaction: raising inside it would roll
        # the expiry back along with everything else.
        _expire(transaction)
        raise ESignResponseStale()
    if not proceed:
        return CallbackOutcome(transaction=transaction, status=transaction.status)

    return _complete(transaction, parsed)


def _gate(provider_name: str, parsed: ESignProviderResponse):
    """Lock the transaction, apply the state gate, and mark it ``SIGNING``.

    Returns ``(transaction, proceed, expired)``. ``proceed`` is False when the
    callback is a duplicate or the ESP reported a failure, both of which are
    answered with a redirect rather than more work; ``expired`` means the
    callback arrived past the grace period and must be refused.
    """

    with db_transaction.atomic():
        transaction = (
            ESignTransaction.objects.select_for_update()
            .filter(
                provider=provider_name,
                provider_transaction_id=parsed.provider_transaction_id,
            )
            .first()
        )
        if transaction is None:
            raise ESignTransactionNotFound()

        if transaction.status == ESignStatus.SUCCESS.value:
            # Never produce a second signed file for the same transaction.
            return transaction, False, False
        if transaction.status == ESignStatus.SIGNING.value:
            # Another worker holds it; answer without reprocessing.
            return transaction, False, False
        if transaction.status in (ESignStatus.FAILURE.value, ESignStatus.EXPIRED.value):
            raise ESignNotProcessable(audit={"status": transaction.status})

        if not transaction.is_callback_window_open():
            return transaction, False, True

        if not parsed.success:
            _record_provider_failure(transaction, parsed)
            return transaction, False, False

        transaction.mark_signing()
        return transaction, True, False


def _expire(transaction: ESignTransaction) -> None:
    """Close a transaction whose callback arrived after the grace period."""

    with db_transaction.atomic():
        locked = ESignTransaction.objects.select_for_update().filter(pk=transaction.pk).first()
        if locked is None or locked.status != ESignStatus.PENDING.value:
            return
        locked.mark_expired(message="The signing response arrived after the transaction expired.")
    log_event(EVENT_ESIGN_EXPIRED, transaction)


def _complete(transaction: ESignTransaction, parsed: ESignProviderResponse) -> CallbackOutcome:
    """Embed the signature, store the signed PDF and mark the row ``SUCCESS``."""

    pkcs7 = _decode_signature(transaction, parsed)

    files = get_file_client()
    try:
        prepared = files.get_content(
            transaction.placeholder_file_id, max_bytes=prepared_document_max_bytes()
        )
    except ESignError as exc:
        raise _fail(transaction, exc, parsed) from exc
    except Exception as exc:
        raise _fail(transaction, ESignFileStorageError(), parsed) from exc

    try:
        signed = get_pdf_client().embed_signature(prepared, pkcs7, transaction.signature_field_name)
    except ESignError as exc:
        raise _fail(transaction, exc, parsed) from exc
    except Exception as exc:
        raise _fail(transaction, ESignPDFEmbedError(), parsed) from exc
    log_event(EVENT_SIGNATURE_EMBEDDED, transaction, signed_size=len(signed))

    try:
        signed_file_id = files.upload(
            signed,
            filename=f"{transaction.source_file_id}{SIGNED_FILENAME_SUFFIX}",
            file_type=FILE_TYPE_SIGNED_PDF,
            user_id=actor_id(transaction.signer),
            organization_id=transaction.organization_id,
            tags=artefact_tags(module=transaction.module, entity_id=transaction.entity_id),
        )
    except ESignError as exc:
        raise _fail(transaction, ESignSignedUploadError(), parsed) from exc
    except Exception as exc:
        raise _fail(transaction, ESignSignedUploadError(), parsed) from exc
    log_event(EVENT_SIGNED_STORED, transaction, signed_file_id=signed_file_id)

    # Compare-and-set on SIGNING: the embed and upload ran outside any lock, so
    # the reconciler may have failed the row meanwhile and a retry may already
    # exist. Completing the stale in-memory instance would resurrect a FAILURE.
    with db_transaction.atomic():
        locked = ESignTransaction.objects.select_for_update().get(pk=transaction.pk)
        if locked.status != ESignStatus.SIGNING.value:
            log_event(
                EVENT_ESIGN_FAILED,
                locked,
                level=logging.WARNING,
                failure_code=locked.failure_code,
                detail="completion refused; row left SIGNING before the signed PDF was stored",
                orphaned_signed_file_id=signed_file_id,
            )
            return CallbackOutcome(transaction=locked, status=locked.status)
        locked.mark_success(
            signed_file_id=signed_file_id,
            response_audit=_response_audit(parsed),
        )
    log_event(EVENT_ESIGN_SUCCEEDED, locked, signed_file_id=signed_file_id)
    return CallbackOutcome(transaction=locked, status=locked.status)


def _decode_signature(transaction: ESignTransaction, parsed: ESignProviderResponse) -> bytes:
    """Return the PKCS#7 bytes, failing the transaction when unusable."""

    if not parsed.signature:
        raise _fail(transaction, ESignSignatureMissing(), parsed)
    try:
        pkcs7 = base64.b64decode(parsed.signature, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _fail(transaction, ESignSignatureInvalid(), parsed) from exc
    if not pkcs7:
        raise _fail(transaction, ESignSignatureInvalid(), parsed)
    return pkcs7


def _record_provider_failure(transaction: ESignTransaction, parsed: ESignProviderResponse) -> None:
    """Record an ESP-reported failure on the transaction."""

    code = (
        parsed.error_code
        if parsed.error_code in PROVIDER_FAILURE_CODES
        else ESignProviderRejected.code
    )
    message = ESignProviderRejected.default_message
    if code == ESignSignatureMissing.code:
        message = ESignSignatureMissing.default_message
    elif code == ESignSignatureInvalid.code:
        message = ESignSignatureInvalid.default_message

    transaction.mark_failed(code, message, response_audit=_response_audit(parsed))
    log_event(EVENT_ESIGN_FAILED, transaction, failure_code=code)


def _fail(
    transaction: ESignTransaction,
    error: ESignError,
    parsed: ESignProviderResponse,
) -> ESignError:
    """Record ``error`` on ``transaction`` and return it for raising."""

    transaction.mark_failed(error.code, error.message, response_audit=_response_audit(parsed))
    log_event(EVENT_ESIGN_FAILED, transaction, failure_code=error.code)
    error.transaction = transaction
    return error


def _response_audit(parsed: ESignProviderResponse) -> dict:
    """Return the persistable audit for an ESP response.

    Neither the PKCS#7 blob nor the signer certificate itself is stored — only
    the codes and the metadata the provider extracted.
    """

    audit = dict(parsed.response_audit or {})
    audit.setdefault("error_code", parsed.error_code)
    if parsed.error_message:
        audit.setdefault("error_message", parsed.error_message)
    if parsed.signed_at is not None:
        audit.setdefault("signed_at", parsed.signed_at.isoformat())
    return safe_audit(audit)
