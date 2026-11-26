"""Builders shared by the scrutiny service and read-model tests."""

import itertools

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.cases.models import (
    Case,
    CaseContact,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    ContactType,
    ParticipantRole,
)
from apps.cases.services import services as case_services
from apps.cases.services.case_types import (
    EVIDENCE_SCAN_TYPES,
    CaseType,
    DocumentType,
    EvidenceType,
    get_config,
)
from apps.files.tests.factories import make_file
from apps.organizations import services as court_services
from apps.organizations.enums import CourtLevel
from apps.organizations.models import CourtRole, Organization, OrganizationType
from apps.parties.models import Person
from apps.parties.tests.factories import make_address
from apps.scrutiny import court_actions as actions
from apps.scrutiny import ports
from apps.scrutiny.enums import FlagTarget
from apps.scrutiny.models import ScrutinyRound
from apps.scrutiny.services import flags
from apps.users.models import RegistrationStatus

User = get_user_model()
_numbers = itertools.count(1)


# The PRD roles' scrutiny duties, as the actions a role holds (spec 0029 #3.3).
SCRUTINY_OFFICER = actions.SCRUTINY_STAGE
CASE_REGISTERER = actions.REGISTRATION_STAGE


def make_user(*duties, name="User", at=None):
    """Return a registered account past every API gate, allowed ``duties`` at ``at``.

    Each duty is a tuple of actions (``SCRUTINY_OFFICER``, ``CASE_REGISTERER``)
    or one action; they are held through one role assigned at the organization
    ``at`` (an establishment, or a courtroom of one).
    """
    user = User.objects.create_user(
        mobile_number=f"+91910000{next(_numbers):04d}",
        name=name,
        registration_status=RegistrationStatus.COMPLETE,
        terms_version_accepted=settings.CURRENT_TERMS_VERSION,
    )
    if duties:
        grant(user, at, *duties)
    return user


def grant(user, organization, *duties):
    """Give ``user`` a role of its own holding ``duties`` at ``organization``."""
    assert organization is not None, "Say where the actions are held (at=...)."
    held = []
    for duty in duties:
        for action in duty if isinstance(duty, tuple) else (duty,):
            if action not in held:
                held.append(action)
    role = court_services.save_role(
        CourtRole(code=f"TEST_ROLE_{next(_numbers)}", name="Test role"), actor=None
    )
    court_services.set_role_actions(role, held, actor=None)
    if organization.court_level == CourtLevel.COURTROOM:
        court_services.assign_courtroom(user, organization, actor=None)
    court_services.assign_role(user, organization, role, actor=None)
    return role


def make_establishment(code, name):
    """Return a court establishment with no courtroom."""
    return Organization.objects.create(
        code=code,
        name=name,
        organization_type=OrganizationType.MAGISTRATE_COURT,
        court_level=CourtLevel.ESTABLISHMENT,
    )


def add_courtroom(establishment, name):
    return Organization.objects.create(
        code=f"{establishment.code}_{name.upper().replace(' ', '_')}",
        name=name,
        organization_type=OrganizationType.MAGISTRATE_COURT,
        court_level=CourtLevel.COURTROOM,
        parent=establishment,
    )


def _scan(case, evidence_type):
    """Return a new document to be the scan of an evidence item of ``evidence_type``."""
    return CaseDocument.objects.create(
        case=case,
        document=make_file(user=case.created_by),
        document_type=EVIDENCE_SCAN_TYPES[evidence_type],
    )


def add_cheque(case, ordinal, delivered=True, cheque_date="2026-05-01", presented="2026-05-02"):
    """Add a cheque, its return memo and its demand notice, each filed with its own scan."""
    CaseEvidence.objects.create(
        case=case,
        case_document=_scan(case, EvidenceType.CHEQUE),
        evidence_type=EvidenceType.CHEQUE,
        ordinal=ordinal,
        evidence_info={
            "cheque_date": cheque_date,
            "amount": 5205000,
            "cheque_number": "123456",
            "ifsc_code": "SBIN0001234",
            "bank_name": "SBI",
            "bank_branch": "Kochi",
        },
    )
    CaseEvidence.objects.create(
        case=case,
        case_document=_scan(case, EvidenceType.RETURN_MEMO),
        evidence_type=EvidenceType.RETURN_MEMO,
        ordinal=ordinal,
        evidence_info={
            "presentation_date": presented,
            "return_date": "2026-05-05",
            "return_reason": "FUNDS_INSUFFICIENT",
        },
    )
    notice = {
        "nature_of_debt": "LOAN_OR_ADVANCE_REPAYMENT",
        "dispatch_date": "2026-05-10",
        "mode_of_service": "REGISTERED_POST",
        "is_delivered": delivered,
        "accused_replied": False,
        "payment_status": "NO_PAYMENT_MADE",
    }
    if delivered:
        notice["delivery_date"] = "2026-05-12"
    else:
        notice.update(return_date="2026-05-12", non_delivery_reason="UNCLAIMED")
    notice = CaseEvidence.objects.create(
        case=case,
        case_document=_scan(case, EvidenceType.LEGAL_DEMAND_NOTICE),
        evidence_type=EvidenceType.LEGAL_DEMAND_NOTICE,
        ordinal=ordinal,
        evidence_info=notice,
    )
    # Each notice is filed with its proof of dispatch, linked to it.
    CaseDocument.objects.create(
        case=case,
        document=make_file(user=case.created_by),
        document_type=DocumentType.PROOF_OF_DISPATCH,
        case_evidence=notice,
    )
    if delivered:
        # A delivered notice may be filed with its proof of delivery, linked to it.
        CaseDocument.objects.create(
            case=case,
            document=make_file(user=case.created_by),
            document_type=DocumentType.PROOF_OF_DELIVERY_OF_DEMAND_NOTICE,
            case_evidence=notice,
        )


def set_cause_of_action(case, day):
    row = ports.detail(case)
    row.jurisdiction_limitation = {
        "cheque_deposited_by_payee": False,
        "drawer_bank_police_station": "Ernakulam Central",
        "other_complaints_pending": False,
        "cause_of_action_date": day,
        "complaint_filing_date": day,
    }
    row.save()


def enter(case, status):
    case.status = status
    case.save()


def add_address(participant):
    """Give ``participant`` an address on its case, as a party write would (spec 0020 §4.6).

    An individual complainant's is their permanent address too.
    """
    address = make_address()
    CaseContact.objects.create(
        case=participant.case,
        case_participant=participant,
        contact_type=ContactType.ADDRESS,
        address=address,
        ordinal=1,
    )
    if participant.role == ParticipantRole.COMPLAINANT and participant.person_id:
        Person.objects.filter(pk=participant.person_id).update(permanent_address=address)


def complete_filing(case, filer):
    """Add the parties, documents and prayer a case needs to pass the completeness check."""
    # Each party has a number of their own (PRD LIT-3).
    for role, name, mobile_number in [
        (ParticipantRole.COMPLAINANT, "Complainant", "+919876543210"),
        (ParticipantRole.ACCUSED, "Accused", "+919812345678"),
    ]:
        complainant = role == ParticipantRole.COMPLAINANT
        participant = CaseParticipant.objects.create(
            case=case,
            person=Person.objects.create(name=name),
            role=role,
            ordinal=1,
            name_at_filing=name,
            age_at_filing=40 if complainant else None,
            is_party_in_person=complainant,
            party_in_person_affidavit="<p>I ask to appear in person.</p>" if complainant else None,
            resides_within_jurisdiction=None if complainant else True,
        )
        add_address(participant)
        CaseContact.objects.create(
            case=case,
            case_participant=participant,
            contact_type=ContactType.MOBILE_NUMBER,
            value=mobile_number,
            ordinal=1,
        )
        if complainant:
            CaseDocument.objects.create(
                case=case,
                document=make_file(user=filer),
                document_type=DocumentType.IDENTITY_PROOF,
                case_participant=participant,
            )
    for document_type in get_config(case.case_type).required_document_types:
        CaseDocument.objects.create(
            case=case, document=make_file(user=filer), document_type=document_type
        )
    case.affidavit = "<p>The facts above are true.</p>"
    case.save(update_fields=["affidavit"])
    row = ports.detail(case)
    row.adr_other_prayer = {
        "adr_preference": "NO",
        "interim_relief": "Direct the accused to pay interim compensation.",
        "final_relief": "Direct the accused to pay the cheque amount.",
    }
    row.save()


def make_paid_case(filer, court, filing_number=None, **cheque):
    """Return a complete case with one cheque, paid and not yet submitted for scrutiny.

    ``court`` is the filer's ``court_id``: an establishment, a courtroom, another court or None.
    """
    case = Case.objects.create(
        case_type=CaseType.CHEQUE_BOUNCE,
        created_by=filer,
        court=court,
        status=CaseStatus.PENDING_PAYMENT,
        filing_number=filing_number,
        filed_at=timezone.now(),
    )
    add_cheque(case, 1, **cheque)
    complete_filing(case, filer)
    set_cause_of_action(case, timezone.localdate().isoformat())
    return case


def make_case(filer, establishment, filing_number=None, **cheque):
    """Return a complete, paid case with one cheque, just entered scrutiny."""
    case = make_paid_case(filer, establishment, filing_number, **cheque)
    enter(case, CaseStatus.UNDER_SCRUTINY)
    return case


def place_at(case, establishment):
    """Move the case's open round to ``establishment``, as if another deployment served it.

    Every case enters scrutiny at the configured establishment (#2.5), so a
    case at a second establishment is placed there by hand.
    """
    ScrutinyRound.objects.filter(case=case, decision="").update(establishment_id=establishment.pk)
    return case


def open_round(case):
    return ScrutinyRound.objects.get(case=case, decision="")


def code(excinfo):
    return excinfo.value.error.code


def field(excinfo):
    detail = excinfo.value.detail
    return next(iter(detail)) if isinstance(detail, dict) else None


def correct_amount(case, filer, amount=5025000):
    """Change the first cheque's amount as the filer would, through ``apps.cases`` (#5.2)."""
    cheque = CaseEvidence.objects.active().get(
        case=case, evidence_type=EvidenceType.CHEQUE, ordinal=1
    )
    return case_services.update_evidence(
        cheque, filer, evidence_info={**cheque.evidence_info, "amount": amount}
    )


def draft_field(case, user, ref, note="Check this date.", **kwargs):
    return flags.draft(
        case.pk, user, target_type=FlagTarget.FIELD, target_ref=ref, note=note, **kwargs
    )
