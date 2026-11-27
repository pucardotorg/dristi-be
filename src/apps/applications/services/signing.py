"""Signing (spec 0033 #6.7, ``ALC-28``).

Only the user in *Raised by* signs, never a clerk or junior, by any method;
enforced here, not by hiding a button. ``record_signature`` takes a signed file
and a method and nothing specific to e-sign, so DSC, mobile OTP and batch
signing call it when they land.
"""

import logging
import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import NotFound

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.esign import errors as esign_errors
from apps.esign.constants import EntityType, ESignStatus
from apps.esign.exceptions import ESignError
from apps.esign.models import ESignTransaction
from apps.esign.services.initiation import initiate_esign
from apps.files.documents import discard_documents, document_error, store_documents

from .. import access, conf, errors
from ..enums import ApplicationStatus, SigningMethod
from ..models import Application
from . import common, drafting, submission
from .common import Action

logger = logging.getLogger(__name__)

S = ApplicationStatus
MODULE = "applications"
PDF_ONLY = {"application/pdf"}


def can_sign_application(*, user, entity_type, entity_id, organization_id=None, file_id=None):
    """The ``APPLICATION`` e-sign authorizer (#6.7).

    A direct ``/esign/_esign`` for an application is refused unless the caller
    is its *Raised by*, it is ``PENDING_SIGNATURE`` and the file is its copy to sign.
    """
    try:
        application = Application.objects.select_related("application_type").get(
            pk=uuid.UUID(str(entity_id))
        )
    except (ValueError, Application.DoesNotExist):
        return False
    return (
        application.status == S.PENDING_SIGNATURE
        and bool(application.signing_file_id)
        and (file_id is None or str(file_id) == application.signing_file_id)
        and access.is_signer(application, user)
    )


def _signer_locked(application_id, user):
    try:
        application = common.lock(application_id)
    except Application.DoesNotExist as exc:
        raise NotFound("Application not found.") from exc
    if not access.can_see(application, user):
        raise NotFound("Application not found.")
    common.require(application, Action.SIGN)
    if not access.is_signer(application, user):
        raise BusinessError(errors.NOT_THE_SIGNER)
    return application


def _require_method(method):
    if method not in conf.signing_methods():
        raise BusinessError(errors.SIGNING_METHOD_NOT_ENABLED, field="method")


def initiate(application_id, user, *, method, sign_placeholder=None):
    """``POST /applications/{id}/sign/`` with ``AADHAAR_ESIGN``: start e-sign (#6.7 steps 1-3)."""
    _require_method(method)
    if method != SigningMethod.AADHAAR_ESIGN:
        # DSC has no module yet; upload uses its own endpoint.
        raise BusinessError(errors.SIGNING_METHOD_NOT_ENABLED, field="method")
    with transaction.atomic():
        application = _signer_locked(application_id, user)
        drafting.require_hearing_upcoming(application)
        drafting.require_target_pending(application)
    placeholder = dict(sign_placeholder or {})
    try:
        return initiate_esign(
            user=user,
            module=MODULE,
            file_id=application.signing_file_id,
            entity_type=EntityType.APPLICATION.value,
            entity_id=str(application.pk),
            organization_id=application.case.court_id,
            sign_placeholder=placeholder,
        )
    except ESignError as exc:
        raise esign_errors.api_error(exc) from exc


def confirm(application_id, user, *, transaction_id):
    """``POST /applications/{id}/sign/confirm/`` (#6.7): record a successful e-sign, idempotently."""
    with transaction.atomic():
        try:
            application = common.lock(application_id)
        except Application.DoesNotExist as exc:
            raise NotFound("Application not found.") from exc
        if not access.can_see(application, user):
            raise NotFound("Application not found.")
        esign = ESignTransaction.objects.filter(
            pk=transaction_id,
            entity_type=EntityType.APPLICATION.value,
            entity_id=str(application.pk),
        ).first()
        recorded = (
            application.transitions.filter(
                action=Action.SIGN, metadata__esign_transaction_id=str(transaction_id)
            ).exists()
            if esign is not None
            else False
        )
        if recorded:
            return application
        common.require(application, Action.SIGN)
        if not access.is_signer(application, user):
            raise BusinessError(errors.NOT_THE_SIGNER)
        if (
            esign is None
            or esign.status != ESignStatus.SUCCESS.value
            or esign.signer_id != user.pk
            or esign.source_file_id != application.signing_file_id
            or not esign.signed_file_id
        ):
            raise BusinessError(errors.SIGNATURE_NOT_VALID)
        return record_signature(
            application,
            esign.signed_file_id,
            SigningMethod.AADHAAR_ESIGN,
            user,
            transaction_id=str(esign.pk),
        )


def upload_signed_copy(application_id, user, upload):
    """``POST /applications/{id}/sign/upload/`` where a state enables it (#6.7, question 21)."""
    _require_method(SigningMethod.UPLOAD_SIGNED_COPY)
    problem = document_error(upload, {k: v for k, v in _formats().items() if k in PDF_ONLY})
    if problem:
        raise BusinessError(errors.DOCUMENT_NOT_ACCEPTED, f"The file {problem}", field="file")
    with transaction.atomic():
        application = _signer_locked(application_id, user)
        drafting.require_hearing_upcoming(application)
        drafting.require_target_pending(application)
        try:
            file_ids = store_documents(
                [upload], user_id=user.pk, tags=["applications", str(application.pk), "signed"]
            )
        except DjangoValidationError as exc:
            raise BusinessError(errors.DOCUMENT_NOT_ACCEPTED, field="file") from exc
        try:
            return record_signature(
                application, file_ids[0], SigningMethod.UPLOAD_SIGNED_COPY, user
            )
        except Exception:
            discard_documents(file_ids)
            raise


def _formats():
    from apps.files.documents import ACCEPTED_FORMATS

    return ACCEPTED_FORMATS


def record_signature(application, signed_file_id, method, actor, *, transaction_id=None):
    """Record the signature on the locked application, then payment or submission (#6.7, #6.8)."""
    common.require(application, Action.SIGN)
    if not signed_file_id:
        raise BusinessError(api_errors.REQUIRED, field="signed_file_id")
    application.signed_file_id = str(signed_file_id)
    metadata = {"method": str(method)}
    if transaction_id:
        metadata["esign_transaction_id"] = str(transaction_id)
    submission.after_signature(application, actor, metadata)
    return application
