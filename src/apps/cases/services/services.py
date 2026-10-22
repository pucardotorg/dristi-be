"""Case filing: draft sessions, lazy case creation, documents, evidence, details.

``POST /cases`` creates only a draft session in the cache (spec 0021 §2.2).
The case row and its type-specific detail row are created by the first save
that carries data, in the same transaction as that data (spec 0021 §9.1).

Every write is refused once the case has left ``DRAFT_IN_PROGRESS``: what the
court reviews must not change underneath it. Every write also touches the
case's ``updated_at``, which listings show and concurrent-edit checks use.
"""

import logging
import uuid

from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail, NotFound

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.files import documents

from .. import errors
from ..models import Case, CaseDocument, CaseEvidence, CaseStatus
from .case_types import get_config, schema_errors

logger = logging.getLogger(__name__)

DRAFT_SESSION_TTL_SECONDS = 60 * 60 * 24
DRAFT_CACHE_KEY = "cases:draft:{draft_session_id}"

# Tag on every stored case document, so they can be found in apps.files.
DOCUMENT_TAG = "cases"

# Distinguishes "not sent" from an explicit ``None`` in partial updates.
_UNSET = object()

# The common code each JSON Schema keyword's failure is reported with; any
# other keyword (pattern, format, minimum …) is a plain invalid value.
SCHEMA_KEYWORD_ERRORS = {
    "required": api_errors.REQUIRED,
    "type": api_errors.INCORRECT_TYPE,
    "enum": api_errors.INVALID_CHOICE,
    "const": api_errors.INVALID_CHOICE,
}


# Draft sessions and case resolution


def start_draft(user, case_type, court_id=None):
    """Cache a new draft session for ``user`` and return it. Nothing is written to the DB.

    ``court_id``, when given, is applied to the case when the first save creates it.
    """
    draft = {
        "draft_session_id": str(uuid.uuid4()),
        "case_type": case_type,
        "court_id": str(court_id) if court_id else None,
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
    """Return the case type of ``user``'s editable case or live draft session.

    For writes: raises ``NotFound`` for anything else, and ``CASE_NOT_EDITABLE``
    for a submitted case. Lets a write be validated against its case type
    before a case is created or a file is stored.
    """
    case = _get_owned_case(case_or_draft_id, user)
    if case is not None:
        _ensure_editable(case)
        return case.case_type
    draft = _get_owned_draft(case_or_draft_id, user)
    if draft is not None:
        return draft["case_type"]
    raise NotFound("Case or draft session not found.")


def get_or_create_case(case_or_draft_id, user):
    """Return ``user``'s editable case, creating it from their draft session on first save.

    Must run inside ``transaction.atomic()`` so the case and the data saved
    with it commit or roll back together.

    The case takes the draft session id as its primary key, so concurrent
    first saves on one draft all insert the same row: the database lets one
    through and ``get_or_create`` hands the others that row. Exactly one case
    is created per draft.
    """
    case = _get_owned_case(case_or_draft_id, user)
    if case is not None:
        _ensure_editable(case)
        return case

    draft = _get_owned_draft(case_or_draft_id, user)
    if draft is None:
        # A concurrent first save may have created the case, and dropped the
        # draft, since the lookup above.
        case = get_case(case_or_draft_id, user)
        _ensure_editable(case)
        return case

    case, created = Case.objects.get_or_create(
        pk=uuid.UUID(str(case_or_draft_id)),
        defaults={
            "case_type": draft["case_type"],
            "court_id": draft.get("court_id"),
            "created_by": user,
            "updated_by": user,
        },
    )
    if created:
        detail_model = get_config(case.case_type).get_detail_model()
        detail_model.objects.create(case=case, created_by=user, updated_by=user)
        key = _get_draft_key(case_or_draft_id)
        transaction.on_commit(lambda: cache.delete(key))
    return case


def _ensure_editable(case):
    """Raise ``CASE_NOT_EDITABLE`` unless the case is still a draft."""
    if case.status != CaseStatus.DRAFT_IN_PROGRESS:
        raise BusinessError(errors.CASE_NOT_EDITABLE)


def _touch(case, user):
    """Record that ``user`` just changed something on ``case``.

    A plain ``update()``: only the timestamps move, so it is not a version
    worth keeping in the case's history.
    """
    Case.objects.filter(pk=case.pk).update(updated_at=timezone.now(), updated_by=user)


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
    """Raise ``NOT_ACCEPTED_FOR_CASE_TYPE`` on ``field`` unless ``value`` is in ``allowed``."""
    if value not in allowed:
        raise BusinessError(
            errors.NOT_ACCEPTED_FOR_CASE_TYPE,
            f"'{value}' is not accepted for {case_type} cases. Must be one of: {', '.join(allowed)}.",
            field=field,
        )


# Documents (spec 0021 §3)


def add_document(case_or_draft_id, user, upload, document_type):
    """Store ``upload`` and file it under the case, creating the case on first save.

    The upload has already passed ``apps.files.documents.document_error``
    (content, extension and size), in the serializer. The file is written to
    storage before the database transaction, as ``apps.files`` requires; if the
    transaction fails the file is deleted again.
    """
    case_type = get_case_type(case_or_draft_id, user)
    allowed = get_config(case_type).document_types
    _require_allowed(document_type, allowed, "document_type", case_type)
    file_id = _store_file(upload, user, case_type)
    try:
        with transaction.atomic():
            case = get_or_create_case(case_or_draft_id, user)
            document = CaseDocument.objects.create(
                case=case,
                document_id=file_id,
                document_type=document_type,
                created_by=user,
                updated_by=user,
            )
            _touch(case, user)
            return document
    except Exception:
        documents.discard_documents([file_id])
        raise


def remove_document(case_document_id, user):
    """Soft-delete a case document. The stored file is kept.

    Evidence that pointed at it is unlinked, so no evidence keeps showing a
    document that is no longer part of the case.
    """
    with transaction.atomic():
        document = _get_active_case_item(CaseDocument, case_document_id, user)
        _ensure_editable(document.case)
        document.is_active = False
        document.updated_by = user
        document.save(update_fields=["is_active", "updated_by", "updated_at"])
        # One save per row, not update(), so each unlink is kept in history.
        for evidence in document.evidence.active():
            evidence.case_document = None
            evidence.updated_by = user
            evidence.save(update_fields=["case_document", "updated_by", "updated_at"])
        _touch(document.case, user)


def _store_file(upload, user, case_type):
    try:
        (file_id,) = documents.store_documents(
            [upload], user_id=user.pk, tags=[DOCUMENT_TAG, case_type]
        )
    except DjangoValidationError as exc:
        raise serializers.ValidationError({"file": exc.messages}) from exc
    return file_id


# Evidence (spec 0021 §5.1)


def validate_evidence(case_type, evidence_type, evidence_info):
    """Raise a 400 unless ``case_type`` accepts ``evidence_type`` and the info fits its schema."""
    schemas = get_config(case_type).evidence_schemas
    _require_allowed(evidence_type, tuple(schemas), "evidence_type", case_type)
    _validate_schema(schemas[evidence_type], evidence_info, "evidence_info")


def _validate_schema(schema, data, field):
    """Raise a 400 listing every way ``data``, sent as ``field``, breaks ``schema``.

    Each error is reported on the path to the offending value, such as
    ``evidence_info.cheque_number``; one about the object as a whole (a
    missing or unknown key) on ``field`` itself.
    """
    detail = {}
    for problem in schema_errors(schema, data):
        code = SCHEMA_KEYWORD_ERRORS.get(problem.keyword, api_errors.INVALID).code
        path = f"{field}.{problem.path}" if problem.path else field
        detail.setdefault(path, []).append(ErrorDetail(problem.message, code=code))
    if detail:
        raise serializers.ValidationError(detail)


def _require_case_document(case, case_document_id):
    """Raise ``DOCUMENT_NOT_ON_CASE`` unless ``case_document_id`` is an active document of ``case``."""
    if not CaseDocument.objects.active().filter(pk=case_document_id, case=case).exists():
        raise BusinessError(errors.DOCUMENT_NOT_ON_CASE, field="case_document_id")


def add_evidence(case_or_draft_id, user, *, evidence_type, evidence_info, case_document_id=None):
    """Add evidence with the next ordinal for its type, creating the case on first save."""
    validate_evidence(get_case_type(case_or_draft_id, user), evidence_type, evidence_info)
    with transaction.atomic():
        case = get_or_create_case(case_or_draft_id, user)
        # Serialises ordinal assignment for the case.
        Case.objects.select_for_update().filter(pk=case.pk).first()

        if case_document_id is not None:
            _require_case_document(case, case_document_id)

        last = (
            CaseEvidence.objects.active()
            .filter(case=case, evidence_type=evidence_type)
            .aggregate(last=Max("ordinal"))["last"]
        )
        evidence = CaseEvidence.objects.create(
            case=case,
            case_document_id=case_document_id,
            evidence_type=evidence_type,
            ordinal=(last or 0) + 1,
            evidence_info=evidence_info,
            created_by=user,
            updated_by=user,
        )
        _touch(case, user)
        return evidence


def get_evidence(case_evidence_id, user):
    """Return active evidence on one of ``user``'s cases, or raise ``NotFound``."""
    return _get_active_case_item(CaseEvidence, case_evidence_id, user)


def update_evidence(evidence, user, *, evidence_info=_UNSET, case_document_id=_UNSET):
    """Replace ``evidence_info`` and/or (re)link a document; the type cannot change.

    ``case_document_id=None`` unlinks the document; leaving it out keeps the
    current link. This is how a scan uploaded after the evidence was entered is
    linked to it (spec 0020 §11.4).
    """
    _ensure_editable(evidence.case)
    fields = ["updated_by", "updated_at"]
    if evidence_info is not _UNSET:
        validate_evidence(evidence.case.case_type, evidence.evidence_type, evidence_info)
        evidence.evidence_info = evidence_info
        fields.append("evidence_info")
    if case_document_id is not _UNSET:
        if case_document_id is not None:
            _require_case_document(evidence.case, case_document_id)
        evidence.case_document_id = case_document_id
        fields.append("case_document")
    evidence.updated_by = user
    with transaction.atomic():
        evidence.save(update_fields=fields)
        _touch(evidence.case, user)
    return evidence


def remove_evidence(evidence, user):
    """Soft-delete evidence."""
    _ensure_editable(evidence.case)
    evidence.is_active = False
    evidence.updated_by = user
    with transaction.atomic():
        evidence.save(update_fields=["is_active", "updated_by", "updated_at"])
        _touch(evidence.case, user)


def _get_active_case_item(model, object_id, user):
    """Return an active document or evidence row on one of ``user``'s cases.

    Ownership is checked through the item's case, so other users' items are
    not found.
    """
    found = model.objects.active().select_related("case")
    instance = found.filter(pk=object_id, case__created_by=user).first()
    if instance is None:
        raise NotFound(f"{model._meta.verbose_name.capitalize()} not found.")
    return instance


# Case details (spec 0021 §5.3)


def get_details(case_id, user):
    """Return every details section of ``user``'s case."""
    case = get_case(case_id, user)
    config = get_config(case.case_type)
    detail = config.get_detail_model().objects.filter(case=case).first()
    # A missing row reads as one not yet filled in, rather than a 500.
    return {section: getattr(detail, section) if detail else {} for section in config.sections}


def save_details_section(case_or_draft_id, user, section, data):
    """Replace one details section, creating the case on first save."""
    case_type = get_case_type(case_or_draft_id, user)
    schemas = get_config(case_type).section_schemas
    _require_allowed(section, tuple(schemas), "section", case_type)
    _validate_schema(schemas[section], data, "data")
    with transaction.atomic():
        case = get_or_create_case(case_or_draft_id, user)
        detail = _get_or_create_detail_row(case, user)
        setattr(detail, section, data)
        detail.updated_by = user
        detail.save(update_fields=[section, "updated_by", "updated_at"])
        _touch(case, user)
        return case


def _get_or_create_detail_row(case, user):
    """Return the case's detail row, creating it if missing.

    It is normally created with the case, but a case made another way (the
    admin, a shell) may have none; saving a section then creates it instead
    of failing with a 500.
    """
    detail, _ = (
        get_config(case.case_type)
        .get_detail_model()
        .objects.get_or_create(case=case, defaults={"created_by": user, "updated_by": user})
    )
    return detail
