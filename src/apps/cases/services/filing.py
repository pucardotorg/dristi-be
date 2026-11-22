"""Preview, completeness check, status transitions and signing (spec 0021 §6–8).

The lifecycle moves forward one step at a time, each step checking its own
precondition:

    DRAFT_IN_PROGRESS --submit-for-signing--> PENDING_SIGN      (filing is complete)
    PENDING_SIGN      --submit-for-payment--> PENDING_PAYMENT   (every signer has signed)
    PENDING_PAYMENT   --submit-for-scrutiny-> UNDER_SCRUTINY    (filed_at is set)

    PENDING_CORRECTION --return-to-signing--> PENDING_SIGN      (complete; signatures cleared)

Scrutiny calls ``return_to_signing`` when the filer submits a correction, so
the corrected case is signed again from scratch.

The transitions live here rather than in the workflow service (spec 0021 §7,
option a). Leaving ``DRAFT_IN_PROGRESS`` freezes the filing: every write in
``services`` and ``participants`` is refused from then on.
"""

import re

from django.core.cache import cache
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.esign.constants import EntityType, ESignStatus
from apps.esign.models import ESignTransaction
from apps.parties.models import PAN_CIN_REQUIRED_MESSAGE

from .. import errors
from ..models import (
    EVIDENCE_ORDERING,
    FILING_SIDE_ROLES,
    PARTICIPANT_ORDERING,
    POA_MANDATE_ORDERING,
    POLICE_STATION_ROLES,
    REPRESENTATION_ORDERING,
    SIGNING_ROLES,
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    ContactType,
    ParticipantRole,
    PoaMandate,
    Representation,
    has_visible_text,
    scan_type_message,
)
from ..serializers import CasePreviewSerializer
from .case_types import (
    EVIDENCE_SCAN_TYPES,
    DocumentType,
    EvidenceType,
    evidence_errors,
    get_config,
    section_errors,
)
from .contacts import contacts_of, first, load_contacts
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


def _filing_side(user):
    """Match the cases ``user`` is on the filing side of.

    The filer, an active complainant or POA holder who is the user, or an
    active advocate of a complainant.
    """
    return (
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


def _find_case(found, case_id):
    case = found.filter(pk=case_id).distinct().first()
    if case is None:
        raise NotFound("Case not found.")
    return case


def get_viewable_case(case_id, user):
    """Return a case ``user`` may preview, or raise ``NotFound`` (spec 0021 §9.6).

    The filing side and staff holding ``cases.view_case`` may. Anyone else,
    the accused and witnesses included, is told the case does not exist.
    """
    if user.has_perm("cases.view_case"):
        return _find_case(Case.objects.all(), case_id)
    return _find_case(Case.objects.filter(_filing_side(user)), case_id)


def get_filing_side_case(case_id, user):
    """Return a case ``user`` may act on as its filing side, or raise ``NotFound``.

    As ``get_viewable_case`` without the staff ``cases.view_case`` reading
    access: viewing a case is no right to answer for its filer.
    """
    return _find_case(Case.objects.filter(_filing_side(user)), case_id)


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
            .select_related("witness", "institution", "person")
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
    load_contacts(case.active_participants)
    case.detail_sections = get_detail_sections(case)
    return case


# Completeness check (spec 0021 §6.3)

# The parties who give their own mobile number and age to file: an individual
# complainant or an institution's authorised representative (PRD LIT-3, LIT-5,
# LIT-22, LIT-24), and a POA holder (LIT-11, LIT-13).
MOBILE_AND_AGE_ROLES = (ParticipantRole.COMPLAINANT, ParticipantRole.POA_HOLDER)
# The roles whose mobile numbers an individual complainant's may not share
# (PRD LIT-3), and whose own may not be an advocate's on the case.
DISTINCT_NUMBER_ROLES = (
    ParticipantRole.COMPLAINANT,
    ParticipantRole.ACCUSED,
    ParticipantRole.POA_HOLDER,
    ParticipantRole.WITNESS,
)
# The PRD's wording (LIT-3).
ADVOCATE_NUMBER_MESSAGE = "Please do not enter the advocate's number here."


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


def _number_key(value):
    """Return the form a phone number is compared in: its digits, without India's prefix.

    A person's number is stored in E.164 form (``+919876543210``); an
    institution's may be written as dialled locally, grouped or not
    (``98765 43210``, ``(080) 2233-4455``). So only the digits are compared,
    without the +91 country code or the leading 0 of a domestic number.
    """
    digits = re.sub(r"\D", "", value)
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]
    return digits


def _mobile_keys(contacts):
    """Return the compared form of every mobile number in ``contacts``."""
    return {
        _number_key(row.value)
        for row in contacts
        if row.contact_type == ContactType.MOBILE_NUMBER and row.value
    }


def _reachable(contacts):
    """Return whether ``contacts`` hold a mobile number or an email."""
    return any(
        row.contact_type in (ContactType.MOBILE_NUMBER, ContactType.EMAIL) for row in contacts
    )


def _unreachable_message(whose):
    """Return the end of the message for an accused with no mobile number, email or declaration."""
    return f"has no mobile number or email, and {whose} contact details are not declared unknown."


def _advocate_numbers(case):
    """Return ``{compared number: user ids}`` of the advocates actively on ``case``."""
    advocates = {}
    for number, user_id in (
        Representation.objects.active()
        .filter(case=case)
        .values_list("advocate__user__mobile_number", "advocate__user_id")
    ):
        if number:
            advocates.setdefault(_number_key(number), set()).add(user_id)
    return advocates


def _shared_number_errors(case, participants):
    """Return ``(field, message)`` for each participant whose number is not theirs alone.

    PRD LIT-3: an individual complainant's may not be another complainant's,
    accused's or witness's (their own, or their institution's on this case), nor
    that of a POA holder acting for them; a POA holder acting only for a
    co-complainant may share it. No individual complainant's, accused's (or accused
    institution's), POA holder's or witness's may be an advocate's on the case,
    whichever side the advocate is for. The same person in another role (a
    complainant who is also a co-complainant's POA holder) shares it rightly,
    and so does an advocate who is the participant. ``participants`` are the
    case's active ones, in ``PARTICIPANT_ORDERING``, with their contacts loaded.
    """
    # Whose numbers they are: (participant, label, person id or None, numbers).
    # An institution's are listed once, named after its first participant.
    holders = []
    institutions = set()
    for participant in participants:
        if participant.role not in DISTINCT_NUMBER_ROLES:
            continue
        own, of_institution = contacts_of(participant)
        label = f"{participant.get_role_display()} #{participant.ordinal}"
        holders.append((participant, label, participant.person_id, _mobile_keys(own)))
        if participant.institution_id and participant.institution_id not in institutions:
            institutions.add(participant.institution_id)
            holders.append(
                (participant, f"{label}'s institution", None, _mobile_keys(of_institution))
            )
    # Each complainant's own POA holders: {represented participant id: holder ids}.
    poa_holders_of = {}
    for represented_id, holder_id in (
        PoaMandate.objects.active()
        .filter(case=case)
        .values_list("represented_participant_id", "poa_participant_id")
    ):
        poa_holders_of.setdefault(represented_id, set()).add(holder_id)
    advocates = _advocate_numbers(case)

    def is_advocates(numbers, user_id=None):
        return any(advocates.get(number, set()) - {user_id} for number in numbers)

    problems = []
    accused_institutions = set()
    for participant in participants:
        if participant.role not in DISTINCT_NUMBER_ROLES:
            continue
        individual_complainant = (
            participant.role == ParticipantRole.COMPLAINANT
            and participant.person_id
            and not participant.institution_id
        )
        # A complainant institution's numbers, and its representative's, are not compared.
        if participant.role == ParticipantRole.COMPLAINANT and not individual_complainant:
            continue
        field = f"participants.{participant.id}"
        label = f"{participant.get_role_display()} #{participant.ordinal}"
        own, of_institution = contacts_of(participant)
        mine = _mobile_keys(own)
        if individual_complainant:
            for other, other_label, person_id, theirs in holders:
                if other.pk == participant.pk or person_id == participant.person_id:
                    continue
                if other.role == ParticipantRole.POA_HOLDER and other.pk not in (
                    poa_holders_of.get(participant.pk, set())
                ):
                    continue
                if mine & theirs:
                    problems.append((field, f"{label}'s mobile number is also {other_label}'s."))
        user_id = participant.person.user_id if participant.person_id else None
        if is_advocates(mine, user_id):
            problems.append((field, f"{label}: {ADVOCATE_NUMBER_MESSAGE}"))
        # An accused institution's, once, on its first participant.
        if (
            participant.role == ParticipantRole.ACCUSED
            and participant.institution_id
            and participant.institution_id not in accused_institutions
        ):
            accused_institutions.add(participant.institution_id)
            if is_advocates(_mobile_keys(of_institution)):
                problems.append((field, f"{label}'s institution: {ADVOCATE_NUMBER_MESSAGE}"))
    return problems


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

    ordered = load_contacts(
        participants.select_related("institution", "person").order_by(*PARTICIPANT_ORDERING)
    )
    # Each accused institution, once for everyone summoned for it: its first
    # participant, whether it can be reached, and whether it names a person.
    # Each accused person is reached on their own (PRD ACC-6/7, ACC-16/17).
    accused_institutions = {}
    unreachable_people = set()
    for participant in ordered:
        field = f"participants.{participant.id}"
        label = f"{participant.get_role_display()} #{participant.ordinal}"
        # An institution with no person acting for it is named by the
        # institution's name, so a missing one is reported once, as that.
        if participant.institution_id and not participant.entity_name_at_filing:
            error(field, f"{label}'s institution has no name.")
        if participant.role != ParticipantRole.WITNESS:
            if not participant.name_at_filing and participant.person_id:
                error(field, f"{label} has no name.")
        elif not (participant.name_at_filing or participant.designation_at_filing):
            error(field, f"{label} has no name or designation.")
        own, of_institution = contacts_of(participant)
        served = of_institution if participant.institution_id else own
        if not first(served, ContactType.ADDRESS):
            error(field, f"{label} has no address.")
        # A complainant institution's authorised representative, or a person
        # responsible for an accused one, is reached at their own address too.
        acts_for_institution = participant.person_id and participant.institution_id
        if acts_for_institution and not first(own, ContactType.ADDRESS):
            error(field, f"{label} acts for an institution but has no address of their own.")
        if participant.role in MOBILE_AND_AGE_ROLES:
            # Only a complainant may be an institution (``INSTITUTION_ROLES``).
            if participant.institution_id and not participant.person_id:
                error(field, f"{label}'s institution has no authorised representative.")
            # The individual's own: an institution's number is not its representative's.
            elif not first(own, ContactType.MOBILE_NUMBER):
                error(field, f"{label} has no mobile number.")
            # From the date of birth when known, else the stated age.
            if participant.person_id and participant.age_at_filing is None:
                error(field, f"{label} has no age.")
        if participant.role == ParticipantRole.ACCUSED:
            if participant.person_id and not (
                participant.contact_details_unknown_declared or _reachable(own)
            ):
                unreachable_people.add(participant.pk)
            if participant.institution_id:
                entry = accused_institutions.setdefault(
                    participant.institution_id,
                    {
                        "participant": participant,
                        # The institution's own contacts, the same for all of them.
                        "reachable": _reachable(of_institution),
                        "declared": False,
                        "has_person": False,
                    },
                )
                entry["declared"] = (
                    entry["declared"] or participant.institution_contact_details_unknown_declared
                )
                entry["has_person"] = entry["has_person"] or bool(participant.person_id)
        address_rows = [
            row for row in [*own, *of_institution] if row.contact_type == ContactType.ADDRESS
        ]
        for row in address_rows:
            if missing := row.address.missing_fields:
                error(field, f"{label} has an incomplete address (missing {', '.join(missing)}).")
        # Stored only when it is not their first address, which is otherwise
        # their permanent one too (§6.4).
        permanent = first(own, ContactType.PERMANENT_ADDRESS)
        if permanent is not None and permanent.address.missing_fields:
            error(
                field,
                f"{label} has an incomplete permanent address "
                f"(missing {', '.join(permanent.address.missing_fields)}).",
            )
        if participant.role in POLICE_STATION_ROLES and any(
            not row.address.police_station for row in address_rows
        ):
            error(field, f"{label} has an address with no police station.")
        # A complainant's authorised representative (PRD LIT-25a); the
        # designation of a person responsible for an accused one is optional (ACC-15).
        if (
            acts_for_institution
            and participant.role == ParticipantRole.COMPLAINANT
            and not participant.designation_at_filing
        ):
            error(field, f"{label} acts for an institution but has no designation.")
        institution = participant.institution
        if institution is not None and not institution.entity_type:
            error(field, f"{label}'s institution has no entity type.")
        if (
            participant.role == ParticipantRole.COMPLAINANT
            and institution is not None
            and not (institution.pan or institution.cin or institution.pan_cin_skip_declared)
        ):
            error(field, f"{label}: {PAN_CIN_REQUIRED_MESSAGE}")

    # An institution's are reported once, on its first participant; then the
    # participant's own.
    for participant in ordered:
        if participant.role != ParticipantRole.ACCUSED:
            continue
        field = f"participants.{participant.id}"
        label = f"Accused #{participant.ordinal}"
        entry = accused_institutions.get(participant.institution_id)
        if entry is not None and entry["participant"] is participant:
            if not entry["has_person"]:
                error(field, f"{label}'s institution names no person responsible.")
            if not (entry["reachable"] or entry["declared"]):
                error(field, f"{label}'s institution {_unreachable_message('its')}")
        if participant.pk in unreachable_people:
            error(field, f"{label} {_unreachable_message('their')}")

    for field, message in _shared_number_errors(case, ordered):
        error(field, message)

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

    if not has_visible_text(case.affidavit):
        error("affidavit", "The affidavit is required.")

    documents = list(
        CaseDocument.objects.active()
        .filter(case=case)
        .only("id", "document_type", "case_participant_id", "case_evidence_id")
    )
    uploaded = {document.document_type for document in documents}

    def linked(document_type, link):
        """Return the ids that active documents of ``document_type`` are linked to by ``link``."""
        return {
            getattr(document, link)
            for document in documents
            if document.document_type == document_type and getattr(document, link)
        }

    # Per-party documents must be linked to their party (spec 0021 §6.3).
    with_identity = linked(DocumentType.IDENTITY_PROOF, "case_participant_id")
    with_vakalatnama = linked(DocumentType.VAKALATNAMA, "case_participant_id")
    for complainant in complainants:
        if complainant.id not in with_identity:
            error(
                "documents.IDENTITY_PROOF",
                f"Complainant #{complainant.ordinal} has no identity proof.",
            )
        if complainant.id in represented and complainant.id not in with_vakalatnama:
            error(
                "documents.VAKALATNAMA",
                f"Complainant #{complainant.ordinal} has an advocate but no vakalatnama.",
            )
    with_poa_document = linked(DocumentType.POA_DOCUMENT, "case_participant_id")
    acting_for = list(
        CaseParticipant.objects.active()
        .filter(
            case=case,
            pk__in=PoaMandate.objects.active().filter(case=case).values("represented_participant"),
        )
        .only("id", "role", "ordinal")
        .order_by(*PARTICIPANT_ORDERING)
    )
    for party in acting_for:
        if party.id not in with_poa_document:
            error(
                "documents.POA_DOCUMENT",
                f"{party.get_role_display()} #{party.ordinal} acts through a POA holder "
                "but has no POA document.",
            )
    # A complainant who says a power of attorney was given (PRD LIT-10) needs
    # the holder, the holder's ID card (DCM-10) and the POA document (DCM-11).
    # The document of one who has a holder is asked for above.
    acting_for_ids = {party.id for party in acting_for}
    holders_of = {}
    for mandate in (
        PoaMandate.objects.active()
        .filter(case=case, poa_participant__is_active=True)
        .select_related("poa_participant")
        .order_by(*POA_MANDATE_ORDERING)
    ):
        holders_of.setdefault(mandate.represented_participant_id, []).append(
            mandate.poa_participant
        )
    without_identity = set()
    for complainant in complainants:
        if not complainant.poa_given:
            continue
        label = f"Complainant #{complainant.ordinal}"
        if complainant.id not in holders_of:
            error(
                f"participants.{complainant.id}",
                f"{label} has given a power of attorney but has no POA holder.",
            )
        if complainant.id not in acting_for_ids and complainant.id not in with_poa_document:
            error(
                "documents.POA_DOCUMENT",
                f"{label} has given a power of attorney but has no POA document.",
            )
        # A holder acting for several complainants is reported once.
        for holder in holders_of.get(complainant.id, []):
            if holder.id not in with_identity and holder.id not in without_identity:
                without_identity.add(holder.id)
                error(
                    "documents.IDENTITY_PROOF",
                    f"POA holder #{holder.ordinal} has no identity proof.",
                )
    scan_types = set(EVIDENCE_SCAN_TYPES.values())
    for document_type in config.required_document_types:
        # An evidence item's scan is asked for on the item, below.
        if document_type not in uploaded and document_type not in scan_types:
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
    # Each demand notice needs its own proof of dispatch (PRD DCM-4). Its proof
    # of delivery is optional (DCM-5).
    with_dispatch_proof = linked(DocumentType.PROOF_OF_DISPATCH, "case_evidence_id")
    for item in evidence:
        if (
            item.evidence_type == EvidenceType.LEGAL_DEMAND_NOTICE
            and item.id not in with_dispatch_proof
        ):
            error(
                "documents.PROOF_OF_DISPATCH",
                f"Demand notice #{item.ordinal} has no proof of dispatch.",
            )
    # Writes already check these; a rule tightened since then is caught here.
    # Each cheque, return memo and demand notice is filed with its own scan,
    # linked from the item, of its type. That no two items share one is a
    # database rule (``cases_case_evidence_unique_active_scan``).
    document_types = {document.id: document.document_type for document in documents}
    for item in evidence:
        scan_type = EVIDENCE_SCAN_TYPES.get(item.evidence_type)
        label = EvidenceType(item.evidence_type).label
        if scan_type and not item.case_document_id:
            error(f"documents.{scan_type}", f"{label} #{item.ordinal} has no scan linked.")
        elif (
            item.case_document_id
            and scan_type
            and document_types.get(item.case_document_id) != scan_type
        ):
            error(
                f"evidence.{item.evidence_type}",
                f"{label} #{item.ordinal}: {scan_type_message(scan_type)}",
            )
        has_schema = item.evidence_type in config.evidence_schemas
        for problem in (
            evidence_errors(config, item.evidence_type, item.evidence_info) if has_schema else []
        ):
            error(f"evidence.{item.evidence_type}", f"{label} #{item.ordinal}: {problem}")

    if config.evidence_set_checks:
        for evidence_type, message in config.evidence_set_checks(evidence):
            error(f"evidence.{evidence_type}", message)

    # An unsaved section is still ``{}``, which fails its required fields here.
    for section, data in get_detail_sections(case).items():
        for problem in section_errors(config, section, data):
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
    only precondition until one records the payment. A case resubmitted after
    correction keeps its first filing date: limitation and delay run from it.
    """
    return _transition(
        case_id,
        user,
        CaseStatus.PENDING_PAYMENT,
        CaseStatus.UNDER_SCRUTINY,
        filed_at=lambda case: case.filed_at or timezone.now(),
    )


def _transition(case_id, user, from_status, to_status, check=None, **fields):
    """Move ``user``'s case from ``from_status`` to ``to_status`` once ``check`` passes.

    The case row is locked, so two concurrent submissions cannot both pass the
    status check. A plain ``save()``, so each step is kept in the case's history.
    A callable value in ``fields`` is called with the locked case.
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
            setattr(case, field, value(case) if callable(value) else value)
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


def return_to_signing(case):
    """Send the locked, corrected ``case`` back to PENDING_SIGN with no signatures.

    Any edit invalidates all signatures (spec 0024 ``LIFE-13``, ``SIG-07``), so
    the case is never back in PENDING_SIGN with an earlier signature still
    counted. The old e-sign transactions are kept; only the participants stop
    counting them. A plain ``save()``, so the new entry is kept in the case's
    history and ``_check_signature`` dates signatures from it.

    Correction can remove parties, evidence and documents, so the corrected
    filing must pass the completeness check again, as at ``submit_for_signing``.
    """
    if case.status != CaseStatus.PENDING_CORRECTION:
        raise BusinessError(
            errors.INVALID_STATUS_TRANSITION,
            f"Only a case in {CaseStatus.PENDING_CORRECTION} can return to "
            f"{CaseStatus.PENDING_SIGN}; this one is {case.status}.",
        )
    problems = validation_errors(case)
    if problems:
        _raise_not_ready(errors.FILING_INCOMPLETE, problems)
    CaseParticipant.objects.filter(case=case, has_signed=True).update(
        has_signed=False, signature_document=None, updated_at=timezone.now()
    )
    case.status = CaseStatus.PENDING_SIGN
    case.save()
    clear_preview_cache(case.pk)


def _submitted_for_signing_at(case):
    """Return when ``case`` last entered PENDING_SIGN, or None.

    A corrected case enters it again, so this is the first PENDING_SIGN
    history row after the last row in any other status. Rows are ordered by
    ``history_id``, the insertion order: consecutive saves can share a
    ``history_date`` on a coarse clock.
    """
    left = (
        case.history.exclude(status=CaseStatus.PENDING_SIGN)
        .order_by("-history_id")
        .values_list("history_id", flat=True)
        .first()
    )
    entries = case.history.filter(status=CaseStatus.PENDING_SIGN)
    if left is not None:
        entries = entries.filter(history_id__gt=left)
    return entries.order_by("history_id").values_list("history_date", flat=True).first()


def _check_signature(case, participant, esign, signature_document_id):
    """Refuse an e-signature that is not this participant's signature of this filing."""
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
    submitted_at = _submitted_for_signing_at(case)
    if esign.completed_at is None or submitted_at is None or esign.completed_at < submitted_at:
        raise errors.SIGNED_BEFORE_SUBMISSION.validation_error(
            {"signature_document_id": [errors.SIGNED_BEFORE_SUBMISSION.message]}
        )
