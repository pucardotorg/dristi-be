"""Initiation: prepare the PDF, store it, create the transaction, build the request.

Order matters (spec 0015 #2, #9). Everything that can fail without leaving a
trace happens before the row is created, so a failed initiation stores nothing;
once the row exists, a failure is recorded on it as ``FAILURE`` and the prepared
document is kept for a retry.
"""

import re
from dataclasses import dataclass

from django.db import IntegrityError
from django.db import transaction as db_transaction
from django.utils import timezone

from .. import conf, permissions
from ..clients import get_file_client, get_pdf_client
from ..clients.pdf import PreparedDocument
from ..constants import (
    ACTIVE_STATUSES,
    EVENT_ESIGN_FAILED,
    EVENT_ESIGN_INITIATED,
    EVENT_PDF_PREPARED,
    EVENT_PLACEHOLDER_STORED,
    EVENT_PROVIDER_REQUEST_BUILT,
    FILE_TAG_ESIGN,
    FILE_TYPE_PDF,
    PDF_CONTENT_TYPE,
    PLACEHOLDER_FILENAME_SUFFIX,
    ESignStatus,
)
from ..exceptions import (
    ESignAlreadyInProgress,
    ESignDisabled,
    ESignError,
    ESignNotAPDF,
    ESignRequestBuildFailed,
)
from ..log import log_event
from ..models import ESignTransaction
from ..providers import ESignInitiation, get_provider

# Audit keys that must never be persisted even if a provider offers them. The
# anchored group keeps descriptive metadata (``signature_count``,
# ``certificate_subject``) while dropping the blobs themselves.
SENSITIVE_AUDIT_KEY = re.compile(
    r"secret|password|passphrase|private|pkcs7|aadhaar|otp|keystore"
    r"|(^|_)(key|cert|certificate|signature)$",
    re.IGNORECASE,
)

# Longest audit string persisted; anything longer is a blob, not metadata.
MAX_AUDIT_VALUE_LENGTH = 256


@dataclass(frozen=True)
class InitiationResult:
    """A created transaction together with the form the browser must post."""

    transaction: ESignTransaction
    initiation: ESignInitiation


def initiate_esign(
    *,
    user,
    module: str,
    file_id: str,
    entity_type: str = "",
    entity_id: str = "",
    organization_id=None,
    sign_placeholder: dict | None = None,
) -> InitiationResult:
    """Start a signing transaction for ``file_id`` and return the ESP form."""

    if not conf.is_enabled():
        raise ESignDisabled()

    provider = get_provider()
    placeholder = dict(sign_placeholder or {})

    permissions.check_can_sign(
        user=user,
        entity_type=entity_type,
        entity_id=entity_id,
        organization_id=organization_id,
    )

    _reject_if_in_progress(file_id=file_id, entity_type=entity_type, entity_id=entity_id)

    prepared = prepare_document(file_id=file_id, sign_placeholder=placeholder)
    placeholder_file_id = store_placeholder(
        prepared.prepared_document,
        file_id=file_id,
        user=user,
        module=module,
        entity_id=entity_id,
        organization_id=organization_id,
    )

    transaction = ESignTransaction.objects.create(
        organization_id=organization_id,
        module=module,
        entity_type=entity_type,
        entity_id=entity_id,
        signer=user if _is_persisted_user(user) else None,
        provider=provider.name,
        source_file_id=str(file_id),
        placeholder_file_id=placeholder_file_id,
        sign_placeholder=placeholder,
        document_hash=prepared.document_hash,
        signature_field_name=prepared.field_name,
        status=ESignStatus.PENDING.value,
        expires_at=timezone.now() + conf.transaction_ttl(),
        created_by=user if _is_persisted_user(user) else None,
        updated_by=user if _is_persisted_user(user) else None,
    )

    initiation = build_provider_request(transaction, provider=provider)

    log_event(
        EVENT_ESIGN_INITIATED,
        transaction,
        entity_type=transaction.entity_type,
        entity_id=transaction.entity_id,
        attempt_count=transaction.attempt_count,
    )
    return InitiationResult(transaction=transaction, initiation=initiation)


def _reject_if_in_progress(*, file_id: str, entity_type: str, entity_id: str) -> None:
    """Refuse a fresh initiation while the document is already being signed.

    Checked before any PDF work so a duplicate call stores nothing. A retry of
    a failed/expired attempt goes through ``_retry`` instead, which reuses the
    prepared document; this guard only blocks a *new* attempt stacking on top of
    a live one. It is an application-level check, so the narrow window between
    two simultaneous initiations is not closed here — the common case it targets
    is a client calling ``_esign`` repeatedly.
    """

    if (
        ESignTransaction.objects.filter(
            source_file_id=str(file_id),
            entity_type=entity_type,
            entity_id=entity_id,
            status__in=ACTIVE_STATUSES,
        )
        .only("id")
        .exists()
    ):
        raise ESignAlreadyInProgress()


def prepare_document(*, file_id: str, sign_placeholder: dict) -> PreparedDocument:
    """Fetch the source PDF and have the PDF Service reserve a container."""

    files = get_file_client()
    metadata = files.get_metadata(file_id)
    content_type = (metadata.get("content_type") or "").split(";")[0].strip().lower()
    if content_type != PDF_CONTENT_TYPE:
        raise ESignNotAPDF()

    content = files.get_content(file_id)
    prepared = get_pdf_client().prepare_for_signing(content, sign_placeholder)
    log_event(
        EVENT_PDF_PREPARED,
        None,
        source_file_id=str(file_id),
        field_name=prepared.field_name,
    )
    return prepared


def store_placeholder(
    document: bytes,
    *,
    file_id: str,
    user,
    module: str,
    entity_id: str = "",
    organization_id=None,
) -> str:
    """Store the prepared PDF as a new file and return its id."""

    placeholder_file_id = get_file_client().upload(
        document,
        filename=f"{file_id}{PLACEHOLDER_FILENAME_SUFFIX}",
        file_type=FILE_TYPE_PDF,
        user_id=actor_id(user),
        organization_id=organization_id,
        tags=artefact_tags(module=module, entity_id=entity_id),
    )
    log_event(
        EVENT_PLACEHOLDER_STORED,
        None,
        module=module,
        placeholder_file_id=placeholder_file_id,
    )
    return placeholder_file_id


def build_provider_request(transaction: ESignTransaction, *, provider=None) -> ESignInitiation:
    """Ask the provider for the ESP form and persist its correlation id."""

    provider = provider or get_provider()
    try:
        initiation = provider.build_initiation(transaction, transaction.document_hash)
    except ESignError as exc:
        _fail(transaction, exc)
        raise
    except Exception as exc:
        error = ESignRequestBuildFailed()
        _fail(transaction, error)
        raise error from exc

    transaction.provider_transaction_id = initiation.provider_transaction_id
    transaction.request_audit = safe_audit(initiation.request_audit)
    try:
        # Its own transaction, so a duplicate id does not leave an outer
        # atomic block unusable for the failure we are about to record.
        with db_transaction.atomic():
            transaction.save(
                update_fields=["provider_transaction_id", "request_audit", "updated_at"]
            )
    except IntegrityError as exc:
        transaction.refresh_from_db(fields=["provider_transaction_id"])
        error = ESignRequestBuildFailed(
            "A signing request with this transaction id already exists."
        )
        _fail(transaction, error)
        raise error from exc

    log_event(
        EVENT_PROVIDER_REQUEST_BUILT,
        transaction,
        esign_url=initiation.esign_url,
        form_field_names=sorted(initiation.form_fields),
    )
    return initiation


def artefact_tags(*, module: str, entity_id: str = "") -> list[str]:
    """Return the discovery tags for an eSign artefact (spec 0015 #4.2).

    ``esign``, the module and the entity id — the three values a support query
    through ``search_file()`` starts from.
    """

    tags = [FILE_TAG_ESIGN]
    for value in (module, entity_id):
        if value:
            tags.append(str(value))
    return tags


def actor_id(user) -> str:
    """Return the user id to record against an upload, or the system actor."""

    if _is_persisted_user(user):
        return str(user.pk)
    return conf.system_actor_id()


def safe_audit(audit) -> dict:
    """Return a JSON-safe audit dict with sensitive keys removed."""

    if not isinstance(audit, dict):
        return {}
    cleaned = {}
    for key, value in audit.items():
        name = str(key)
        if SENSITIVE_AUDIT_KEY.search(name):
            continue
        if isinstance(value, dict):
            cleaned[name] = safe_audit(value)
        elif isinstance(value, list | tuple):
            cleaned[name] = [
                _safe_audit_value(item)
                for item in value
                if isinstance(item, str | int | float | bool)
            ]
        elif value is None or isinstance(value, str | int | float | bool):
            cleaned[name] = _safe_audit_value(value)
        else:
            cleaned[name] = _safe_audit_value(str(value))
    return cleaned


def _safe_audit_value(value):
    """Truncate audit strings so a blob can never be persisted as metadata."""

    if isinstance(value, str) and len(value) > MAX_AUDIT_VALUE_LENGTH:
        return value[:MAX_AUDIT_VALUE_LENGTH]
    return value


def _fail(transaction: ESignTransaction, error: ESignError) -> None:
    """Record ``error`` on ``transaction`` and log the failure."""

    transaction.mark_failed(error.code, error.message, response_audit=transaction.response_audit)
    log_event(EVENT_ESIGN_FAILED, transaction, failure_code=error.code)


def _is_persisted_user(user) -> bool:
    """Whether ``user`` is a saved account that can be referenced by a row."""

    return bool(user is not None and getattr(user, "pk", None) and user.is_authenticated)
