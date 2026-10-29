"""Preview, completeness check, status transitions and signing (spec 0021 §6–8).

The lifecycle moves forward one step at a time, each step checking its own
precondition:

    DRAFT_IN_PROGRESS --submit-for-signing--> PENDING_SIGN      (filing is complete)
    PENDING_SIGN      --submit-for-payment--> PENDING_PAYMENT   (every signer has signed)
    PENDING_PAYMENT   --submit-for-scrutiny-> UNDER_SCRUTINY    (filed_at is set)

The transitions live here rather than in the workflow service (spec 0021 §7,
option a). Leaving ``DRAFT_IN_PROGRESS`` freezes the filing: every write in
``services`` and ``participants`` is refused from then on.
"""

from django.core.cache import cache
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.esign.constants import EntityType, ESignStatus
from apps.esign.models import ESignTransaction

from .. import errors
from ..models import (
    EVIDENCE_ORDERING,
    FILING_SIDE_ROLES,
    PARTICIPANT_ORDERING,
    POA_MANDATE_ORDERING,
    REPRESENTATION_ORDERING,
    SIGNING_ROLES,
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    ParticipantRole,
    PoaMandate,
    Representation,
    has_visible_text,
)
from ..serializers import CasePreviewSerializer
from .case_types import DocumentType, EvidenceType, get_config, schema_errors
from .services import (
    PREVIEW_TTL_SECONDS,
    clear_preview_cache,
    get_case,
    get_detail_sections,
    get_preview_cache_key,
    lock_case,
    touch,
)

# Preview (spec 0021 §6.1, §6.2)


def get_viewable_case(case_id, user):
    """Return a case ``user`` may preview, or raise ``NotFound`` (spec 0021 §9.6).

    The filer, an active complainant or POA holder who is the user, an active
    advocate of a complainant, and staff holding ``cases.view_case`` may.
    Anyone else, the accused and witnesses included, is told the case does
    not exist.
    """
    viewable = (
        Q(created_by=user)
        | Q(
            participants__person__user=user,
            participants__is_active=True,
            participants__role__in=FILING_SIDE_ROLES,
        )
        | Q(
            representations__advocate__user=user,
            representations__is_active=True,
            representations__case_participant__role__in=FILING_SIDE_ROLES,
        )
    )
    found = (
        Case.objects.all() if user.has_perm("cases.view_case") else Case.objects.filter(viewable)
    )
    case = found.filter(pk=case_id).distinct().first()
    if case is None:
        raise NotFound("Case not found.")
    return case


def get_preview(case_id, user):
    """Return the whole filing as one object, from the cache when it is there.

    Every write clears the entry (``services.touch``), so a cached preview is
    never stale. Access is checked before the cache is read.
    """
    case = get_viewable_case(case_id, user)
    key = get_preview_cache_key(case.pk)
    data = cache.get(key)
    if data is None:
        data = dict(CasePreviewSerializer(_load_preview(case.pk)).data)
        cache.set(key, data, PREVIEW_TTL_SECONDS)
    return data


def _load_preview(case_id):
    """Load the case with every active row the preview shows, in a fixed number of queries."""
    case = Case.objects.prefetch_related(
        Prefetch(
            "participants",
            queryset=CaseParticipant.objects.active()
            .select_related("address", "witness")
            .order_by(*PARTICIPANT_ORDERING),
            to_attr="active_participants",
        ),
        Prefetch(
            "representations",
            queryset=Representation.objects.active()
            .select_related("advocate")
            .order_by(*REPRESENTATION_ORDERING),
            to_attr="active_representations",
        ),
        Prefetch(
            "poa_mandates",
            queryset=PoaMandate.objects.active()
            .select_related("poa_participant")
            .order_by(*POA_MANDATE_ORDERING),
            to_attr="active_poa_mandates",
        ),
        Prefetch(
            "evidence",
            queryset=CaseEvidence.objects.active().order_by(*EVIDENCE_ORDERING),
            to_attr="active_evidence",
        ),
        Prefetch(
            "documents",
            queryset=CaseDocument.objects.active()
            .select_related("document")
            .order_by("document_type", "created_at"),
            to_attr="active_documents",
        ),
    ).get(pk=case_id)
    case.detail_sections = get_detail_sections(case)
    return case


# Completeness check (spec 0021 §6.3)


def validate_case(case_id, user):
    """Return ``(is_valid, errors)`` for ``user``'s case."""
    problems = validation_errors(get_case(case_id, user))
    return not problems, problems


def _error_item(field, message):
    """Return one reason a case is not ready, as the API reports it."""
    return {"field": field, "message": message}


def _raise_not_ready(error, items):
    """Raise ``error`` as a 400 with one error per item, each on its part of the filing."""
    detail = {}
    for item in items:
        detail.setdefault(item["field"], []).append(item["message"])
    raise error.validation_error(detail)


def validation_errors(case):
    """Return every reason ``case`` is not yet complete, as ``{field, message}`` items."""
    problems = []

    def error(field, message):
        problems.append(_error_item(field, message))

    config = get_config(case.case_type)
    participants = CaseParticipant.objects.active().filter(case=case)
    complainants = list(participants.filter(role=ParticipantRole.COMPLAINANT).order_by("ordinal"))
    if not complainants:
        error("participants.complainants", "At least one active complainant is required.")
    if not participants.filter(role=ParticipantRole.ACCUSED).exists():
        error("participants.accused", "At least one active accused is required.")

    represented = set(
        Representation.objects.active().filter(case=case).values_list("case_participant", flat=True)
    )
    for complainant in complainants:
        if complainant.id not in represented and not complainant.is_party_in_person:
            error(
                f"participants.{complainant.id}",
                f"Complainant #{complainant.ordinal} has no advocate and is not marked "
                "as party-in-person.",
            )
        if complainant.is_party_in_person and not has_visible_text(
            complainant.party_in_person_affidavit
        ):
            error(
                f"participants.{complainant.id}",
                f"Complainant #{complainant.ordinal} appears in person but has no "
                "party-in-person affidavit.",
            )

    # Writes refuse empty editor output; this also catches what reached the
    # database another way (the admin, a shell).
    if not has_visible_text(case.affidavit):
        error("affidavit", "The affidavit is required.")

    # Vakalatnamas and POA documents belong to the case, not to one
    # representation or mandate (spec 0021 §3.4), so one of each is enough.
    uploaded = set(
        CaseDocument.objects.active().filter(case=case).values_list("document_type", flat=True)
    )
    if represented and DocumentType.VAKALATNAMA not in uploaded:
        error("documents.VAKALATNAMA", "A vakalatnama is required when an advocate is engaged.")
    if (
        PoaMandate.objects.active().filter(case=case).exists()
        and DocumentType.POA_DOCUMENT not in uploaded
    ):
        error("documents.POA_DOCUMENT", "A POA document is required when a POA holder acts.")
    for document_type in config.required_document_types:
        if document_type not in uploaded:
            error(
                f"documents.{document_type}",
                f"Document type {document_type} is required but not uploaded.",
            )

    evidence = list(CaseEvidence.objects.active().filter(case=case).order_by("ordinal"))
    present = {item.evidence_type for item in evidence}
    for evidence_type in config.required_evidence_types:
        if evidence_type not in present:
            label = EvidenceType(evidence_type).label.lower()
            error(f"evidence.{evidence_type}", f"At least one {label} evidence is required.")
    # Writes already check these; a schema tightened since then is caught here.
    for item in evidence:
        schema = config.evidence_schemas.get(item.evidence_type)
        for problem in schema_errors(schema, item.evidence_info) if schema else []:
            label = EvidenceType(item.evidence_type).label
            error(f"evidence.{item.evidence_type}", f"{label} #{item.ordinal}: {problem}")

    # An unsaved section is still ``{}``, which fails its required fields here.
    for section, data in get_detail_sections(case).items():
        for problem in schema_errors(config.section_schemas[section], data):
            error(f"details.{section}", str(problem))
    return problems


# Status transitions (spec 0021 §7)


def submit_for_signing(case_id, user):
    """Freeze a complete draft for signing."""

    def check(case):
        problems = validation_errors(case)
        if problems:
            _raise_not_ready(errors.FILING_INCOMPLETE, problems)

    return _transition(case_id, user, CaseStatus.DRAFT_IN_PROGRESS, CaseStatus.PENDING_SIGN, check)


def submit_for_payment(case_id, user):
    """Move a case every signer has signed on to payment."""

    def check(case):
        unsigned = (
            CaseParticipant.objects.active()
            .filter(case=case, role__in=SIGNING_ROLES, has_signed=False)
            .order_by(*PARTICIPANT_ORDERING)
        )
        problems = [
            _error_item(
                f"participants.{participant.id}",
                f"{participant.get_role_display()} #{participant.ordinal} has not signed.",
            )
            for participant in unsigned
        ]
        if problems:
            _raise_not_ready(errors.SIGNATURES_PENDING, problems)

    return _transition(case_id, user, CaseStatus.PENDING_SIGN, CaseStatus.PENDING_PAYMENT, check)


def submit_for_scrutiny(case_id, user):
    """Send a paid case to scrutiny; this is when it counts as filed.

    There is no payment service yet, so being in ``PENDING_PAYMENT`` is the
    only precondition until one records the payment.
    """
    return _transition(
        case_id,
        user,
        CaseStatus.PENDING_PAYMENT,
        CaseStatus.UNDER_SCRUTINY,
        filed_at=timezone.now(),
    )


def _transition(case_id, user, from_status, to_status, check=None, **fields):
    """Move ``user``'s case from ``from_status`` to ``to_status`` once ``check`` passes.

    The case row is locked, so two concurrent submissions cannot both pass the
    status check. A plain ``save()``, so each step is kept in the case's history.
    """
    with transaction.atomic():
        case = lock_case(get_case(case_id, user))
        if case.status != from_status:
            raise BusinessError(
                errors.INVALID_STATUS_TRANSITION,
                f"Only a case in {from_status} can move to {to_status}; this one is {case.status}.",
            )
        if check is not None:
            check(case)
        case.status = to_status
        case.updated_by = user
        for field, value in fields.items():
            setattr(case, field, value)
        case.save(update_fields=["status", *fields, "updated_by", "updated_at"])
        clear_preview_cache(case.pk)
    return case


# Signing (spec 0021 §8)


def record_signature(case_id, case_participant_id, user, signature_document_id):
    """Record that a participant has e-signed the filing.

    The e-signing itself happens through ``apps.esign`` first; here the
    document is only accepted if a completed e-sign transaction produced it,
    after the case was submitted for signing, signed by the participant's own
    account where they have one, and not already recorded for anyone else.
    When it was signed is that transaction's ``completed_at``, set on the
    returned participant as ``signed_at``; it is not stored again here.
    """
    with transaction.atomic():
        case = lock_case(get_case(case_id, user))
        if case.status != CaseStatus.PENDING_SIGN:
            raise BusinessError(
                errors.INVALID_STATUS_TRANSITION,
                f"Signatures are recorded only while the case is {CaseStatus.PENDING_SIGN}; "
                f"this one is {case.status}.",
            )
        participant = (
            CaseParticipant.objects.active().filter(pk=case_participant_id, case=case).first()
        )
        if participant is None:
            raise NotFound("Case participant not found.")
        if participant.role not in SIGNING_ROLES:
            raise errors.NOT_A_SIGNER.validation_error(
                {"case_participant_id": [errors.NOT_A_SIGNER.message]}
            )
        if participant.has_signed:
            raise BusinessError(errors.ALREADY_SIGNED)
        esign = ESignTransaction.objects.filter(
            signed_file_id=str(signature_document_id),
            status=ESignStatus.SUCCESS.value,
            entity_type=EntityType.CASE_FILING.value,
            entity_id=str(case.pk),
        ).first()
        if esign is None:
            raise errors.SIGNATURE_NOT_FOUND.validation_error(
                {"signature_document_id": [errors.SIGNATURE_NOT_FOUND.message]}
            )
        _check_signature(case, participant, esign, signature_document_id)
        participant.has_signed = True
        participant.signature_document_id = signature_document_id
        participant.updated_by = user
        participant.save(
            update_fields=["has_signed", "signature_document", "updated_by", "updated_at"]
        )
        touch(case, user)
    participant.signed_at = esign.completed_at
    return participant


def _check_signature(case, participant, esign, signature_document_id):
    """Refuse an e-signature that is not this participant's signature of this filing.

    The case only moves forward and enters PENDING_SIGN once, so its first
    history row in that status is when it was submitted for signing.
    """
    if (
        CaseParticipant.objects.filter(signature_document_id=signature_document_id)
        .exclude(pk=participant.pk)
        .exists()
    ):
        raise errors.SIGNATURE_ALREADY_USED.validation_error(
            {"signature_document_id": [errors.SIGNATURE_ALREADY_USED.message]}
        )
    person = participant.person
    if person is not None and person.user_id is not None and esign.signer_id != person.user_id:
        raise errors.SIGNED_BY_SOMEONE_ELSE.validation_error(
            {"signature_document_id": [errors.SIGNED_BY_SOMEONE_ELSE.message]}
        )
    submitted_at = (
        case.history.filter(status=CaseStatus.PENDING_SIGN)
        .order_by("history_date")
        .values_list("history_date", flat=True)
        .first()
    )
    if esign.completed_at is None or submitted_at is None or esign.completed_at < submitted_at:
        raise errors.SIGNED_BEFORE_SUBMISSION.validation_error(
            {"signature_document_id": [errors.SIGNED_BEFORE_SUBMISSION.message]}
        )
