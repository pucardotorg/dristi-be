"""Case filing: draft sessions, lazy case creation, documents, evidence, details.

``POST /cases`` creates only a draft session in the cache (spec 0021 §2.2).
The case row and its type-specific detail row are created by the first save
that carries data, in the same transaction as that data (spec 0021 §9.1).
"""

import logging
import uuid

import jsonschema
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from apps.files import services as files
from apps.files.models import FileType

from ..models import Case, CaseDocument, CaseEvidence
from .case_types import get_config

logger = logging.getLogger(__name__)

DRAFT_SESSION_TTL_SECONDS = 60 * 60 * 24
DRAFT_CACHE_KEY = "cases:draft:{draft_session_id}"

# Accepted upload content types and the FileType each is stored as.
CONTENT_TYPE_FILE_TYPES = {
    "application/pdf": FileType.PDF,
    "image/jpeg": FileType.IMAGE,
    "image/png": FileType.IMAGE,
}


# Draft sessions and case resolution


def start_draft(user, case_type):
    """Cache a new draft session for ``user`` and return it. Nothing is written to the DB."""
    draft = {
        "draft_session_id": str(uuid.uuid4()),
        "case_type": case_type,
        "created_by": str(user.pk),
        "created_at": timezone.now().isoformat(),
    }
    cache.set(_get_draft_key(draft["draft_session_id"]), draft, DRAFT_SESSION_TTL_SECONDS)
    return draft


def get_case(case_id, user):
    """Return ``user``'s case, or raise ``NotFound``. Other users' cases are not found."""
    case = _get_owned_case(case_id, user)
    if case is None:
        raise NotFound("Case not found.")
    return case


def get_case_type(case_or_draft_id, user):
    """Return the case type of ``user``'s case or live draft session.

    Raises ``NotFound`` for anything else. Lets a write be validated against
    its case type before a case is created or a file is stored.
    """
    case = _get_owned_case(case_or_draft_id, user)
    if case is not None:
        return case.case_type
    draft = _get_owned_draft(case_or_draft_id, user)
    if draft is not None:
        return draft["case_type"]
    raise NotFound("Case or draft session not found.")


def get_or_create_case(case_or_draft_id, user):
    """Return ``user``'s case, creating it from their draft session on first save.

    Must run inside ``transaction.atomic()`` so the case and the data saved
    with it commit or roll back together.

    The case takes the draft session id as its primary key, so concurrent
    first saves on one draft all insert the same row: the database lets one
    through and ``get_or_create`` hands the others that row. Exactly one case
    is created per draft.
    """
    case = _get_owned_case(case_or_draft_id, user)
    if case is not None:
        return case

    draft = _get_owned_draft(case_or_draft_id, user)
    if draft is None:
        # A concurrent first save may have created the case, and dropped the
        # draft, since the lookup above.
        return get_case(case_or_draft_id, user)

    case, created = Case.objects.get_or_create(
        pk=uuid.UUID(str(case_or_draft_id)),
        defaults={"case_type": draft["case_type"], "created_by": user, "updated_by": user},
    )
    if created:
        detail_model = get_config(case.case_type).get_detail_model()
        detail_model.objects.create(case=case, created_by=user, updated_by=user)
        key = _get_draft_key(case_or_draft_id)
        transaction.on_commit(lambda: cache.delete(key))
    return case


def _get_owned_case(case_id, user):
    return Case.objects.filter(pk=case_id, created_by=user).first()


def _get_owned_draft(draft_session_id, user):
    draft = cache.get(_get_draft_key(draft_session_id))
    if draft is None or draft["created_by"] != str(user.pk):
        return None
    return draft


def _get_draft_key(draft_session_id):
    return DRAFT_CACHE_KEY.format(draft_session_id=draft_session_id)


def _require_allowed(value, allowed, field, case_type):
    """Raise a 400 on ``field`` unless ``value`` is allowed for ``case_type``."""
    if value not in allowed:
        raise serializers.ValidationError(
            {
                field: f"'{value}' is not accepted for {case_type} cases. "
                f"Must be one of: {', '.join(allowed)}."
            }
        )


# Documents (spec 0021 §3)


def add_document(case_or_draft_id, user, upload, document_type):
    """Store ``upload`` and file it under the case, creating the case on first save.

    The file is written to storage before the database transaction, as
    ``apps.files`` requires; if the transaction fails the file is deleted again.
    """
    case_type = get_case_type(case_or_draft_id, user)
    allowed = get_config(case_type).document_types
    _require_allowed(document_type, allowed, "document_type", case_type)
    file_id = _store_file(upload, user)
    try:
        with transaction.atomic():
            case = get_or_create_case(case_or_draft_id, user)
            return CaseDocument.objects.create(
                case=case,
                document_id=file_id,
                document_type=document_type,
                created_by=user,
                updated_by=user,
            )
    except Exception:
        _delete_file(file_id)
        raise


def remove_document(case_id, case_document_id, user):
    """Soft-delete a case document. The stored file is kept."""
    document = _get_active_case_item(CaseDocument, case_id, case_document_id, user)
    document.is_active = False
    document.updated_by = user
    document.save(update_fields=["is_active", "updated_by", "updated_at"])


def _store_file(upload, user):
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    payload = {
        "user_id": user.pk,
        "files": [{"file": upload, "file_type": CONTENT_TYPE_FILE_TYPES[content_type]}],
    }
    try:
        result = files.upload_file(payload)
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"file": exc.messages}) from exc
    return result["files"][0]["id"]


def _delete_file(file_id):
    try:
        files.delete_file(file_id)
    except Exception:  # noqa: BLE001 - must not mask the error being handled
        logger.exception("Could not delete case document file %s", file_id)


# Evidence (spec 0021 §5.1)


def validate_evidence(case_type, evidence_type, evidence_info):
    """Raise a 400 unless ``case_type`` accepts ``evidence_type`` and the info fits its schema."""
    schemas = get_config(case_type).evidence_schemas
    _require_allowed(evidence_type, tuple(schemas), "evidence_type", case_type)
    _validate_schema(schemas[evidence_type], evidence_info, "evidence_info")


def _validate_schema(schema, data, field):
    """Raise a 400 on ``field`` listing every way ``data`` breaks ``schema``."""
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    messages = [error.message for error in validator.iter_errors(data)]
    if messages:
        raise serializers.ValidationError({field: messages})


def add_evidence(case_or_draft_id, user, *, evidence_type, evidence_info, case_document_id=None):
    """Add evidence with the next ordinal for its type, creating the case on first save."""
    validate_evidence(get_case_type(case_or_draft_id, user), evidence_type, evidence_info)
    with transaction.atomic():
        case = get_or_create_case(case_or_draft_id, user)
        # Serialises ordinal assignment for the case.
        Case.objects.select_for_update().filter(pk=case.pk).first()

        if (
            case_document_id is not None
            and not CaseDocument.objects.active().filter(pk=case_document_id, case=case).exists()
        ):
            raise serializers.ValidationError(
                {"case_document_id": "No active document with this id on this case."}
            )

        last = (
            CaseEvidence.objects.active()
            .filter(case=case, evidence_type=evidence_type)
            .aggregate(last=Max("ordinal"))["last"]
        )
        return CaseEvidence.objects.create(
            case=case,
            case_document_id=case_document_id,
            evidence_type=evidence_type,
            ordinal=(last or 0) + 1,
            evidence_info=evidence_info,
            created_by=user,
            updated_by=user,
        )


def get_evidence(case_id, case_evidence_id, user):
    """Return active evidence on ``user``'s case, or raise ``NotFound``."""
    return _get_active_case_item(CaseEvidence, case_id, case_evidence_id, user)


def update_evidence(evidence, user, evidence_info):
    """Replace ``evidence_info``. The evidence type cannot change."""
    validate_evidence(evidence.case.case_type, evidence.evidence_type, evidence_info)
    evidence.evidence_info = evidence_info
    evidence.updated_by = user
    evidence.save(update_fields=["evidence_info", "updated_by", "updated_at"])
    return evidence


def remove_evidence(evidence, user):
    """Soft-delete evidence."""
    evidence.is_active = False
    evidence.updated_by = user
    evidence.save(update_fields=["is_active", "updated_by", "updated_at"])


def _get_active_case_item(model, case_id, object_id, user):
    found = model.objects.active().filter(pk=object_id, case_id=case_id, case__created_by=user)
    instance = found.first()
    if instance is None:
        raise NotFound(f"{model._meta.verbose_name.capitalize()} not found.")
    return instance


# Case details (spec 0021 §5.3)


def get_details(case_id, user):
    """Return every details section of ``user``'s case."""
    case = get_case(case_id, user)
    detail = _get_detail_row(case)
    return {section: getattr(detail, section) for section in get_config(case.case_type).sections}


def save_details_section(case_or_draft_id, user, section, data):
    """Replace one details section, creating the case on first save."""
    case_type = get_case_type(case_or_draft_id, user)
    schemas = get_config(case_type).section_schemas
    _require_allowed(section, tuple(schemas), "section", case_type)
    _validate_schema(schemas[section], data, "data")
    with transaction.atomic():
        case = get_or_create_case(case_or_draft_id, user)
        detail = _get_detail_row(case)
        setattr(detail, section, data)
        detail.updated_by = user
        detail.save(update_fields=[section, "updated_by", "updated_at"])
        return case


def _get_detail_row(case):
    return get_config(case.case_type).get_detail_model().objects.get(case=case)
