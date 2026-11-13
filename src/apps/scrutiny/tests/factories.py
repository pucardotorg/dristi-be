"""Builders shared by the scrutiny service and read-model tests."""

import itertools

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.utils import timezone

from apps.cases.models import (
    Case,
    CaseDocument,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    ParticipantRole,
)
from apps.cases.services import services as case_services
from apps.cases.services.case_types import CaseType, EvidenceType, get_config
from apps.files.tests.factories import make_file
from apps.organizations.models import Organization, OrganizationType
from apps.parties.models import Person
from apps.parties.tests.factories import make_address
from apps.scrutiny import ports
from apps.scrutiny.enums import FlagTarget
from apps.scrutiny.models import ScrutinyRound
from apps.scrutiny.services import flags
from apps.users.models import RegistrationStatus

User = get_user_model()
_numbers = itertools.count(1)


def make_user(*roles, name="User"):
    """Return a registered account holding ``roles``, past every API gate."""
    user = User.objects.create_user(
        mobile_number=f"+91910000{next(_numbers):04d}",
        name=name,
        registration_status=RegistrationStatus.COMPLETE,
        terms_version_accepted=settings.CURRENT_TERMS_VERSION,
    )
    for role in roles:
        user.groups.add(Group.objects.get_or_create(name=role)[0])
    return user


def add_courtroom(establishment, name):
    return Organization.objects.create(
        code=name.upper().replace(" ", "_"),
        name=name,
        organization_type=OrganizationType.MAGISTRATE_COURT,
        parent=establishment,
    )


def add_cheque(case, ordinal, delivered=True, cheque_date="2026-05-01", presented="2026-05-02"):
    CaseEvidence.objects.create(
        case=case,
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
        evidence_type=EvidenceType.RETURN_MEMO,
        ordinal=ordinal,
        evidence_info={
            "presentation_date": presented,
            "return_date": "2026-05-05",
            "return_reason": "Funds insufficient",
        },
    )
    notice = {
        "nature_of_debt": "Loan",
        "cheque_issue_reason": "Repayment",
        "dispatch_date": "2026-05-10",
        "mode_of_service": "Registered post",
        "is_delivered": delivered,
        "payment_status": "Unpaid",
    }
    if delivered:
        notice["delivery_date"] = "2026-05-12"
    CaseEvidence.objects.create(
        case=case,
        evidence_type=EvidenceType.LEGAL_DEMAND_NOTICE,
        ordinal=ordinal,
        evidence_info=notice,
    )


def set_cause_of_action(case, day):
    row = ports.detail(case)
    row.jurisdiction_limitation = {"cheque_deposited_by_payee": False, "cause_of_action_date": day}
    row.save()


def enter(case, status):
    case.status = status
    case.save()


def complete_filing(case, filer):
    """Add the parties, documents and prayer a case needs to pass the completeness check."""
    for role, name in [
        (ParticipantRole.COMPLAINANT, "Complainant"),
        (ParticipantRole.ACCUSED, "Accused"),
    ]:
        CaseParticipant.objects.create(
            case=case,
            person=Person.objects.create(name=name),
            role=role,
            ordinal=1,
            name_at_filing=name,
            address=make_address(),
            is_party_in_person=role == ParticipantRole.COMPLAINANT,
        )
    for document_type in get_config(case.case_type).required_document_types:
        CaseDocument.objects.create(
            case=case, document=make_file(user=filer), document_type=document_type
        )
    row = ports.detail(case)
    row.adr_other_prayer = {"final_relief": "Direct the accused to pay the cheque amount."}
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
