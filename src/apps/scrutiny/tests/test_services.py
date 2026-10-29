"""Rounds, flags, decisions and responses through the services (spec 0024 #3–#6, #10)."""

import datetime

import pytest
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.cases.models import Case, CaseEvidence, CaseStatus
from apps.cases.services.case_types import CaseType, EvidenceType
from apps.scrutiny import ports
from apps.scrutiny.enums import (
    CourtRole,
    DocumentIssue,
    FlagStatus,
    FlagTarget,
    RoundDecision,
    RoundStage,
    RoutingReason,
)
from apps.scrutiny.models import ScrutinyRound
from apps.scrutiny.services import flags, rounds

from .factories import (
    add_cheque,
    add_courtroom,
    answer,
    code,
    draft_field,
    enter,
    field,
    make_user,
    open_round,
    set_cause_of_action,
)

pytestmark = pytest.mark.django_db


# Rounds (#4.1)


def test_entering_scrutiny_opens_round_one(case, establishment):
    round_ = open_round(case)
    assert (round_.stage, round_.number, round_.establishment_id) == (
        RoundStage.SCRUTINY,
        1,
        establishment.pk,
    )
    case.save()
    assert ScrutinyRound.objects.filter(case=case).count() == 1


def test_case_without_court_gets_no_round(filer):
    case = Case.objects.create(
        case_type=CaseType.CHEQUE_BOUNCE, created_by=filer, status=CaseStatus.UNDER_SCRUTINY
    )
    assert not ScrutinyRound.objects.filter(case=case).exists()


def test_start_records_first_starter_only(case, officer):
    other = make_user(CourtRole.SCRUTINY_OFFICER)
    rounds.start(case.pk, officer, RoundStage.SCRUTINY)
    rounds.start(case.pk, other, RoundStage.SCRUTINY)
    assert open_round(case).started_by == officer


def test_actions_need_the_stage_role(case, registerer):
    with pytest.raises(BusinessError) as excinfo:
        rounds.start(case.pk, registerer, RoundStage.SCRUTINY)
    assert code(excinfo) == "E09008"
    with pytest.raises(BusinessError) as excinfo:
        rounds.start(case.pk, registerer, RoundStage.REGISTRATION)
    assert code(excinfo) == "E09001"


# Flags (#3.2, #3.3)


def test_field_flag_marks_its_own_cheques_dates(case, officer):
    add_cheque(case, 2)
    created = draft_field(case, officer, "CHQ-8[1]")
    refs = [flag.target_ref for flag in created]
    assert refs == ["CHQ-8[1]", "CHQ-9[1]", "LDN-2[1]", "LDN-6[1]", "JUR-9", "JUR-10"]
    source = created[0]
    assert source.value_at_flag == "2026-05-02"
    assert all(flag.auto_marked_by == source for flag in created[1:])
    assert created[1].note == "Marked because Date of presentation was flagged"


def test_undelivered_notice_marks_its_return_date(case, officer):
    add_cheque(case, 2, delivered=False)
    refs = [flag.target_ref for flag in draft_field(case, officer, "LDN-2[1]")]
    assert refs == ["LDN-2[1]", "LDN-7[1]", "JUR-9", "JUR-10"]


def test_delay_field_marked_only_when_delay_applies(case, officer):
    set_cause_of_action(case, "2026-01-01")
    refs = [flag.target_ref for flag in draft_field(case, officer, "JUR-9")]
    assert refs == ["JUR-9", "JUR-10", "JUR-11"]


@pytest.mark.parametrize(
    ("kwargs", "expected_code", "expected_field"),
    [
        (
            {"target_type": FlagTarget.FIELD, "target_ref": "CHQ-3[5]", "note": "x"},
            "E09003",
            "target_ref",
        ),
        (
            {"target_type": FlagTarget.SECTION, "target_ref": "OTH", "note": "x"},
            "E09003",
            "target_ref",
        ),
        (
            {"target_type": FlagTarget.DOCUMENT, "target_ref": "not-a-uuid", "note": "x"},
            "E09003",
            "target_ref",
        ),
        (
            {"target_type": FlagTarget.FIELD, "target_ref": "CHQ-3[0]", "note": "  "},
            "E09004",
            "note",
        ),
        ({"target_type": FlagTarget.OATH, "target_ref": "x", "note": "x"}, "E09016", "target_ref"),
    ],
)
def test_draft_refuses(case, officer, kwargs, expected_code, expected_field):
    with pytest.raises(BusinessError) as excinfo:
        flags.draft(case.pk, officer, **kwargs)
    assert (code(excinfo), field(excinfo)) == (expected_code, expected_field)


def test_one_live_flag_per_target(case, officer):
    flags.draft(case.pk, officer, target_type=FlagTarget.SECTION, target_ref="LDN", note="x")
    with pytest.raises(BusinessError) as excinfo:
        flags.draft(case.pk, officer, target_type=FlagTarget.SECTION, target_ref="LDN", note="y")
    assert code(excinfo) == "E09009"


def test_save_both_links_and_withdraws_independently(case, officer, document):
    field_flag, issue = draft_field(
        case,
        officer,
        "CHQ-3[0]",
        document_issue={"document_id": document.pk, "reason_code": DocumentIssue.BLURRY_UNREADABLE},
    )
    assert (issue.target_type, issue.linked_flag, field_flag.linked_flag) == (
        FlagTarget.DOCUMENT,
        field_flag,
        issue,
    )
    flags.withdraw(case.pk, field_flag.pk, officer)
    issue.refresh_from_db()
    assert issue.status == FlagStatus.DRAFT


def test_withdraw_keeps_edited_auto_marked_dates(case, officer):
    source, presented, *rest = draft_field(case, officer, "CHQ-1[0]")
    flags.edit(case.pk, presented.pk, officer, note="Presentation date looks wrong too.")
    flags.withdraw(case.pk, source.pk, officer)
    statuses = {flag.target_ref: flag.status for flag in open_round(case).flags.all()}
    assert statuses["CHQ-8[0]"] == FlagStatus.DRAFT
    assert {statuses[flag.target_ref] for flag in rest} == {FlagStatus.WITHDRAWN}


# Send back, correction and re-scrutiny (#4.3, #5, #4.5)


def test_send_back_needs_a_draft(case, officer):
    with pytest.raises(BusinessError) as excinfo:
        rounds.send_back(case.pk, officer)
    assert code(excinfo) == "E09005"


def test_send_back_raises_drafts_and_opens_scope(case, officer):
    set_cause_of_action(case, "2026-01-01")
    draft_field(case, officer, "JUR-10")
    round_ = rounds.send_back(case.pk, officer)
    case.refresh_from_db()
    assert case.status == CaseStatus.PENDING_CORRECTION
    assert round_.decision == RoundDecision.SENT_BACK
    assert {flag.status for flag in round_.flags.all()} == {FlagStatus.RAISED}
    scope = ports.correction_scope(case)
    assert scope["fields"] == ["JUR-10", "JUR-11"]
    assert scope["required"] == ["JUR-11", "JUR-12"]


def test_resubmission_carries_and_resolves(case, officer, filer):
    flag = draft_field(case, officer, "CHQ-3[0]")[0]
    rounds.send_back(case.pk, officer)
    answer(flag, filer)
    enter(case, CaseStatus.UNDER_SCRUTINY)
    second = open_round(case)
    assert (second.number, second.routing_reason) == (2, RoutingReason.RESUBMITTED)
    carried = second.flags.get()
    assert (carried.status, carried.carried_from_id) == (FlagStatus.DRAFT, flag.pk)
    flag.refresh_from_db()
    assert flag.status == FlagStatus.CARRIED
    assert ports.correction_scope(case) is None

    flags.resolve(case.pk, carried.pk, officer)
    flag.refresh_from_db()
    assert flag.status == FlagStatus.RESOLVED


def test_resolve_needs_a_carried_draft(case, officer):
    flag = draft_field(case, officer, "CHQ-3[0]")[0]
    with pytest.raises(BusinessError) as excinfo:
        flags.resolve(case.pk, flag.pk, officer)
    assert code(excinfo) == "E09002"


# Forward and register (#4.4, #6)


def test_forward_and_register_follow_roles(case, officer, officer_registerer):
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, officer_registerer)
    assert code(excinfo) == "E09007"
    with pytest.raises(BusinessError) as excinfo:
        rounds.register_at_scrutiny(case.pk, officer)
    assert code(excinfo) == "E09007"


def test_courtroom_required_when_there_are_several(case, officer, establishment):
    first = add_courtroom(establishment, "Courtroom 1")
    add_courtroom(establishment, "Courtroom 2")
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, officer)
    assert (code(excinfo), field(excinfo)) == ("E09017", "courtroom_id")
    rounds.forward(case.pk, officer, courtroom_id=first.pk)
    case.refresh_from_db()
    assert (case.status, case.court) == (CaseStatus.PENDING_REGISTRATION, first)
    registration = open_round(case)
    assert (registration.stage, registration.courtroom_id) == (RoundStage.REGISTRATION, first.pk)


def test_open_items_travel_with_the_case(case, officer, filer):
    flag = draft_field(case, officer, "CHQ-3[0]")[0]
    rounds.send_back(case.pk, officer)
    answer(flag, filer)
    enter(case, CaseStatus.UNDER_SCRUTINY)
    draft_field(case, officer, "CHQ-1[0]")  # never sent: withdrawn on forward
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, officer)
    assert code(excinfo) == "E09006"
    forwarded = rounds.forward(case.pk, officer, acknowledge_open_items=True)
    assert (forwarded.open_items_acknowledged, forwarded.open_items_at_decision) == (True, 1)
    assert not forwarded.flags.filter(status=FlagStatus.DRAFT, carried_from__isnull=True).exists()

    registration = open_round(case)
    assert registration.flags.get().target_ref == "CHQ-3[0]"


def test_register_at_scrutiny(case, officer_registerer):
    round_ = rounds.register_at_scrutiny(case.pk, officer_registerer)
    case.refresh_from_db()
    assert (round_.decision, case.status) == (RoundDecision.REGISTERED, CaseStatus.REGISTERED)
    assert not ScrutinyRound.objects.filter(case=case, stage=RoundStage.REGISTRATION).exists()


def test_registration_type_required_when_there_are_several(case, officer, monkeypatch):
    monkeypatch.setattr(
        ports,
        "REGISTRATION_TYPES",
        (ports.RegistrationType("ECC", "eCC"), ports.RegistrationType("ECR", "eCR")),
    )
    with pytest.raises(BusinessError) as excinfo:
        rounds.forward(case.pk, officer)
    assert (code(excinfo), field(excinfo)) == ("E09018", "registration_type")
    assert rounds.forward(case.pk, officer, registration_type="ECR").registration_type == "ECR"


def test_set_title(case, officer):
    rounds.set_title(case.pk, officer, complainant="Prateek Agrawal", accused="Deepak Choudhary")
    assert ports.detail(case).additional_details["case_title"]["accused"] == "Deepak Choudhary"


def test_delay_is_measured_against_today(case):
    set_cause_of_action(case, (timezone.localdate() - datetime.timedelta(days=40)).isoformat())
    assert ports.delay_alert(case)


def test_date_chain_passes_through_missing_dates(case, officer):
    # No return memo or notice for cheque 2: its presentation, return and notice dates
    # do not exist, but the jurisdiction dates after them are still marked.
    CaseEvidence.objects.create(
        case=case,
        evidence_type=EvidenceType.CHEQUE,
        ordinal=2,
        evidence_info=CaseEvidence.objects.get(
            case=case, ordinal=1, evidence_type=EvidenceType.CHEQUE
        ).evidence_info,
    )
    refs = [flag.target_ref for flag in draft_field(case, officer, "CHQ-1[1]")]
    assert refs == ["CHQ-1[1]", "JUR-9", "JUR-10"]
