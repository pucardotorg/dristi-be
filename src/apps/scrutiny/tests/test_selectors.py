"""Read models and read access (spec 0024 #7, #8.4, #10)."""

import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.cases.models import (
    Case,
    CaseEvidence,
    CaseParticipant,
    CaseStatus,
    ParticipantRole,
    Representation,
)
from apps.cases.services.case_types import EvidenceType
from apps.organizations.models import Organization, OrganizationType
from apps.parties.models import Person
from apps.parties.tests.factories import make_address
from apps.scrutiny import case_selectors, permissions, ports, selectors
from apps.scrutiny.enums import CourtRole, FlagStatus, FlagTarget, RoundStage, RoutingReason
from apps.scrutiny.models import ScrutinyFlag, ScrutinyRound
from apps.scrutiny.services import flags, responses, rounds
from apps.users.models import AdvocateProfile, ApprovalStatus

from .factories import (
    add_courtroom,
    code,
    correct_amount,
    draft_field,
    enter,
    make_case,
    make_user,
    open_round,
)

pytestmark = pytest.mark.django_db


def list_rows(user, **kwargs):
    found = selectors.scrutiny_list(user, **kwargs)
    return found["counts"], selectors.scrutiny_rows(found["rounds"])


def send_back_and_resubmit(case, officer, filer, explain=True):
    flag = draft_field(case, officer, "CHQ-3[0]", note="Amount reads ₹50,25,000.")[0]
    rounds.send_back(case.pk, officer)
    if explain:
        responses.explain(case.pk, flag.pk, filer, "The amount is right.")
    else:
        correct_amount(case, filer)
    responses.submit_correction(case.pk, filer)
    enter(case, CaseStatus.UNDER_SCRUTINY)
    return flag


def add_party(case, role, name, ordinal):
    return CaseParticipant.objects.create(
        case=case,
        person=Person.objects.create(name=name),
        role=role,
        ordinal=ordinal,
        name_at_filing=name,
        address=make_address(),
    )


# Access (#8.4)


def test_court_reader_needs_a_court_role(case, officer, filer):
    assert permissions.court_case(case.pk, officer)[0] == case
    with pytest.raises(NotFound):
        permissions.court_case(case.pk, filer)
    with pytest.raises(BusinessError) as excinfo:
        permissions.require_court_reader(filer)
    assert code(excinfo) == "E09008"


def test_case_never_in_scrutiny_is_not_found(officer, filer):
    from apps.cases.models import Case
    from apps.cases.services.case_types import CaseType

    draft = Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=filer)
    with pytest.raises(NotFound):
        permissions.court_case(draft.pk, officer)


def test_filing_side_reads_only_its_own_case(case, filer, officer):
    assert permissions.filing_case(case.pk, filer) == case
    with pytest.raises(NotFound):
        permissions.filing_case(case.pk, make_user())


# Scrutiny list (#7.1)


def test_tabs_counts_and_stages(case, officer, filer, establishment):
    sent_back = make_case(filer, establishment, filing_number="F/EST/2026/00002")
    draft_field(sent_back, officer, "CHQ-1[0]")
    rounds.send_back(sent_back.pk, officer)
    forwarded = make_case(filer, establishment, filing_number="F/EST/2026/00003")
    rounds.forward(forwarded.pk, officer)

    counts, rows = list_rows(officer)
    assert counts == {"registry": 1, "advocate": 1, "closed": 1}
    assert [(row["filing_number"], row["stage"]) for row in rows] == [
        ("F/EST/2026/00001", "AWAITING_SCRUTINY")
    ]
    _, rows = list_rows(officer, tab="advocate")
    assert (rows[0]["stage"], rows[0]["reason"]) == ("SENT_BACK", "Sent back with 1 item")
    _, rows = list_rows(officer, tab="closed")
    assert rows[0]["stage"] == "FORWARDED"


def test_claimed_and_search(case, officer, filer, establishment):
    other = make_case(filer, establishment, filing_number="F/EST/2026/00009")
    rounds.start(case.pk, officer, RoundStage.SCRUTINY)
    _, rows = list_rows(officer, claimed="me")
    assert [row["case_id"] for row in rows] == [case.pk]
    assert rows[0]["stage"] == "UNDER_SCRUTINY"
    assert rows[0]["with"]["name"] == "Biju B"
    _, rows = list_rows(officer, claimed="unassigned")
    assert [row["case_id"] for row in rows] == [other.pk]
    _, rows = list_rows(officer, search="00009")
    assert [row["case_id"] for row in rows] == [other.pk]


@pytest.mark.parametrize(
    ("explain", "reason"), [(True, "1 item contested"), (False, "All items answered")]
)
def test_rescrutiny_reason(case, officer, filer, explain, reason):
    send_back_and_resubmit(case, officer, filer, explain=explain)
    _, rows = list_rows(officer)
    assert (rows[0]["stage"], rows[0]["reason"], rows[0]["round"]) == (
        "AWAITING_RESCRUTINY",
        reason,
        2,
    )


def test_rows_take_a_fixed_number_of_queries(officer, filer, establishment):
    def queries_for(count):
        for number in range(count):
            make_case(filer, establishment, filing_number=f"F/Q/{count}/{number}")
        found = selectors.scrutiny_list(officer, search=f"F/Q/{count}/")["rounds"]
        with CaptureQueriesContext(connection) as context:
            rows = selectors.scrutiny_rows(found)
        assert len(rows) == count
        return len(context)

    assert queries_for(2) == queries_for(6)


# Scrutiny detail (#7.2)


def test_detail_marks_flagged_fields_and_actions(case, officer, officer_registerer, document):
    flag = draft_field(case, officer, "CHQ-3[0]")[0]
    round_ = open_round(case)
    detail = selectors.scrutiny_detail(case, round_, officer)
    cheque = next(section for section in detail["sections"] if section["id"] == "CHQ")
    amount = next(field for field in cheque["groups"][0]["fields"] if field["ref"] == "CHQ-3[0]")
    assert (cheque["groups"][0]["title"], amount["value"], amount["flag_id"]) == (
        "Cheque 1",
        5205000,
        flag.pk,
    )
    assert detail["bundle"][0]["document_id"] == document.pk
    assert [item["id"] for item in detail["flags"]["draft"]] == [flag.pk]
    assert isinstance(detail["alerts"], list)
    assert "oaths" not in detail
    assert detail["allowed_actions"] == ["start", "flag", "send_back", "forward", "edit_title"]
    as_both = selectors.scrutiny_detail(case, round_, officer_registerer)["allowed_actions"]
    assert "register" in as_both and "forward" not in as_both


def test_detail_shows_carried_items_with_their_history(case, officer, filer):
    flag = send_back_and_resubmit(case, officer, filer)
    detail = selectors.scrutiny_detail(case, open_round(case), officer)
    carried = detail["flags"]["carried"][0]
    assert carried["carried_from"] == flag.pk
    assert carried["history"][0]["responses"][0]["contested"] is True
    assert [item["id"] for item in detail["flags"]["raised_last_round"]] == [flag.pk]
    assert detail["round"]["summary"].startswith("2 rounds · 1 item open since ")


# Registration (#7.3, #7.4)


def test_registration_list_and_detail(officer, registerer, filer, establishment):
    # Presented after the cheque's validity (SCR-08a).
    case = make_case(filer, establishment, cheque_date="2026-01-01", presented="2026-05-02")
    rounds.forward(case.pk, officer)
    rows = selectors.registration_rows(selectors.registration_list(registerer))
    assert (rows[0]["case_id"], rows[0]["courtroom"]["name"]) == (case.pk, "Establishment")

    round_ = open_round(case)
    detail = selectors.registration_detail(case, round_, registerer)
    assert detail["scrutiny"]["cleared_by"]["name"] == "Biju B"
    assert detail["scrutiny"]["round_count"] == 1
    presented = next(line for line in detail["timeline"] if line["step"] == "PRESENTED")
    assert (presented["qualifier"], presented["warning"]) == (
        "beyond 3 months of the cheque date",
        True,
    )
    assert detail["allowed_actions"] == ["start", "register", "send_back", "edit_title"]


def test_registration_detail_needs_a_forwarded_case(case, officer):
    with pytest.raises(NotFound):
        selectors.registration_detail(case, open_round(case), officer)


# History (#7.5)


def test_history_tells_the_rounds(case, officer, filer):
    rounds.start(case.pk, officer, RoundStage.SCRUTINY)
    send_back_and_resubmit(case, officer, filer)
    found = selectors.history(case)
    assert [entry["text"] for entry in found["entries"]][1:] == [
        "Routed to scrutiny",
        "Scrutiny started · Biju B",
        "Sent back with 1 item · round 1",
        "Resubmitted · 1 of 1 item answered",
        "Returned to scrutiny · 1 item contested",
    ]
    item = found["entries"][3]["items"][0]
    assert item["label"] == "Cheque amount"
    assert item["state"].startswith("answered ")
    filer_view = selectors.history(case, for_filer=True)
    assert "Scrutiny started" in [entry["text"] for entry in filer_view["entries"]]


# Filer correction view (#7.6)


def test_corrections_group_items_and_say_what_is_open(case, officer, filer, document):
    flags.draft(
        case.pk,
        officer,
        target_type=FlagTarget.DOCUMENT,
        target_ref=str(document.pk),
        reason_code="BLURRY_UNREADABLE",
    )
    draft_field(case, officer, "JUR-10")
    assert selectors.corrections(case)["open"] is False
    rounds.send_back(case.pk, officer)
    case.refresh_from_db()
    view = selectors.corrections(case)
    assert (view["open"], view["mode"], view["round"]) == (True, "MARKED", 1)
    assert [item["target_ref"] for item in view["flags"]] == ["JUR-10"]
    assert view["flags"][0]["open"] is True
    assert view["document_issues"][0]["target_ref"] == str(document.pk)


def test_corrections_after_registration_send_back(case, officer, registerer):
    rounds.forward(case.pk, officer)
    rounds.registration_send_back(case.pk, registerer, "Re-check the affidavit.")
    case.refresh_from_db()
    view = selectors.corrections(case)
    assert (view["mode"], view["comment"]) == ("ALL", "Re-check the affidavit.")


def test_cheque_without_its_return_memo_is_flaggable_not_a_broken_check(case, officer):
    CaseEvidence.objects.create(
        case=case,
        evidence_type=EvidenceType.CHEQUE,
        ordinal=2,
        evidence_info={"cheque_date": "2026-05-01", "amount": 100},
    )
    detail = selectors.scrutiny_detail(case, open_round(case), officer)
    missing = [alert for alert in detail["alerts"] if alert["code"] == "DISHONOUR_DETAILS_MISSING"]
    assert [(alert["field_refs"], alert["message"]) for alert in missing] == [
        (
            ["CHQ-8[1]", "CHQ-9[1]"],
            "Cheque 2 is missing its date of presentation, date of return and return reason; "
            "the checks on its dishonour were skipped.",
        )
    ]
    assert "CHECKS_UNAVAILABLE" not in [alert["code"] for alert in detail["alerts"]]
    facts = case_selectors.check_facts(case, timezone.localdate())
    assert [cheque["index"] for cheque in facts["cheques"]] == [0]
    cheque = next(section for section in detail["sections"] if section["id"] == "CHQ")
    second = next(group for group in cheque["groups"] if group["title"] == "Cheque 2")
    assert [(field["ref"], field["value"]) for field in second["fields"]] == [
        ("CHQ-1[1]", "2026-05-01"),
        ("CHQ-3[1]", 100),
        ("CHQ-8[1]", None),
        ("CHQ-9[1]", None),
    ]
    flag = draft_field(case, officer, "CHQ-8[1]", note="No return memo for cheque 2.")[0]
    assert (flag.target_label, flag.value_at_flag) == ("Date of presentation", None)


def test_timeline_has_no_qualifier_for_a_missing_date(officer, filer, establishment):
    case = make_case(filer, establishment)
    CaseEvidence.objects.filter(case=case, evidence_type=EvidenceType.RETURN_MEMO).delete()
    lines = {
        line["step"]: line
        for line in case_selectors.get_registration_timeline(case, None, None, timezone.localdate())
    }
    assert (lines["PRESENTED"]["qualifier"], lines["NOTICE_SENT"]["qualifier"]) == (None, None)
    assert lines["COMPLAINT_FILED"]["qualifier"] == "within 1 month of the cause of action"


def test_rows_for_a_registration_send_back_and_a_registration(
    case, officer, registerer, filer, establishment
):
    rounds.forward(case.pk, officer)
    rounds.registration_send_back(case.pk, registerer, "Re-check the affidavit.")
    _, rows = list_rows(officer, tab="advocate")
    assert (rows[0]["stage"], rows[0]["reason"]) == ("SENT_BACK", "Sent back at registration")

    registered = make_case(filer, establishment, filing_number="F/EST/2026/00007")
    rounds.forward(registered.pk, officer)
    rounds.register(registered.pk, registerer)
    # The row follows the round's decision, not the case status.
    Case.objects.filter(pk=registered.pk).update(status=CaseStatus.UNDER_SCRUTINY)
    _, rows = list_rows(officer, tab="closed")
    assert [(row["stage"], row["reason"]) for row in rows] == [
        ("REGISTERED", f"CC/1/{timezone.now().year}")
    ]


# Edges of the read models


def test_actions_need_an_open_round_and_the_stage_role(case, officer, registerer):
    round_ = open_round(case)
    assert selectors.allowed_actions(round_, {CourtRole.CASE_REGISTERER}) == []
    rounds.forward(case.pk, officer)
    round_.refresh_from_db()
    assert selectors.allowed_actions(round_, {CourtRole.SCRUTINY_OFFICER}) == []
    registration = open_round(case)
    assert selectors.allowed_actions(registration, {CourtRole.SCRUTINY_OFFICER}) == []


def test_lists_filter_by_establishment(case, officer, registerer, filer, establishment):
    elsewhere = Organization.objects.create(
        code="OTHER", name="Other court", organization_type=OrganizationType.MAGISTRATE_COURT
    )
    make_case(filer, elsewhere, filing_number="F/OTH/2026/00001")
    _, rows = list_rows(officer, establishment_id=establishment.pk)
    assert [row["case_id"] for row in rows] == [case.pk]

    rounds.forward(case.pk, officer)
    found = selectors.registration_list(
        registerer, establishment_id=establishment.pk, search="00001"
    )
    assert [round_.case_id for round_ in found] == [case.pk]
    assert not selectors.registration_list(registerer, establishment_id=elsewhere.pk)


def test_rescrutiny_after_a_registration_send_back_has_no_reason(case, officer, registerer, filer):
    rounds.forward(case.pk, officer)
    rounds.registration_send_back(case.pk, registerer, "Re-check the affidavit.")
    correct_amount(case, filer, 2)
    responses.submit_correction(case.pk, filer)
    enter(case, CaseStatus.UNDER_SCRUTINY)
    _, rows = list_rows(officer)
    assert (rows[0]["stage"], rows[0]["reason"]) == ("AWAITING_RESCRUTINY", "")


def test_detail_lists_oaths_where_the_state_requires_them(case, officer, monkeypatch):
    oath = {"id": "O1", "complainant": "Prateek"}
    monkeypatch.setattr(ports, "oath_required", lambda case: True)
    monkeypatch.setattr(ports, "oaths", lambda case: [oath])
    assert selectors.scrutiny_detail(case, open_round(case), officer)["oaths"] == [oath]


def test_list_names_parties_title_and_advocate(case, officer):
    first = add_party(case, ParticipantRole.COMPLAINANT, "Prateek", 1)
    add_party(case, ParticipantRole.COMPLAINANT, "Asha", 2)
    add_party(case, ParticipantRole.ACCUSED, "Deepak", 1)
    advocate = AdvocateProfile.objects.create(
        user=make_user(name="Meera Nair"),
        bar_registration_id="KL/1/2020",
        approval_status=ApprovalStatus.ACCEPTED,
    )
    Representation.objects.create(case=case, advocate=advocate, case_participant=first)
    summary = case_selectors.get_case_summaries([case.pk])[case.pk]
    assert (summary["parties"], summary["advocate"]) == (
        "Prateek and others v. Deepak",
        "Adv. Meera Nair",
    )
    rounds.set_title(case.pk, officer, complainant="Prateek Agrawal", accused="")
    summary = case_selectors.get_case_summaries([case.pk])[case.pk]
    assert summary["parties"] == "Prateek Agrawal v. Deepak"


def test_history_names_the_routing_reason(case):
    ScrutinyRound.objects.filter(case=case).delete()
    rounds.open_round(case, routing_reason=RoutingReason.RANDOM_CHECK)
    entries = selectors.history(case)["entries"]
    assert entries[1]["text"] == "Routed to scrutiny · Random check"


def test_history_says_an_item_was_resolved(case, officer, filer):
    send_back_and_resubmit(case, officer, filer)
    flags.resolve(case.pk, open_round(case).flags.get().pk, officer)
    sent_back = next(e for e in selectors.history(case)["entries"] if e["kind"] == "SENT_BACK")
    assert sent_back["items"][0]["state"].startswith("resolved ")


def test_history_through_registration(case, officer, registerer, filer, establishment):
    rounds.forward(case.pk, officer)
    rounds.registration_send_back(case.pk, registerer, "Re-check the affidavit.")
    correct_amount(case, filer, 2)
    responses.submit_correction(case.pk, filer)
    enter(case, CaseStatus.UNDER_SCRUTINY)
    room = add_courtroom(establishment, "Courtroom 1")
    rounds.forward(case.pk, officer, courtroom_id=room.pk)
    rounds.register(case.pk, registerer)
    case.refresh_from_db()
    entries = selectors.history(case)["entries"]
    returned = next(e for e in entries if e["kind"] == "SENT_BACK_AT_REGISTRATION")
    assert returned["comment"] == "Re-check the affidavit."
    assert [e["text"] for e in entries if e["kind"] in ("FORWARDED", "REGISTERED")] == [
        "Forwarded · Establishment",
        "Forwarded · Courtroom 1",
        f"Registered · CC/1/{timezone.now().year}",
    ]


def test_corrections_show_only_items_sent_to_the_filer(case, officer):
    withdrawn = draft_field(case, officer, "CHQ-3[0]")[0]
    flags.withdraw(case.pk, withdrawn.pk, officer)
    draft_field(case, officer, "JUR-10")
    round_ = rounds.send_back(case.pk, officer)
    # Send back raises every draft; one can only be added after it by hand, in the admin.
    ScrutinyFlag.objects.create(
        round=round_,
        target_type=FlagTarget.SECTION,
        target_ref="LDN",
        target_label="Notice",
        section_id="LDN",
        note="Court's own note.",
        status=FlagStatus.DRAFT,
    )
    case.refresh_from_db()
    assert [item["target_ref"] for item in selectors.corrections(case)["flags"]] == ["JUR-10"]


def test_anonymous_holds_no_court_role(case):
    assert permissions.court_roles(AnonymousUser(), None) == frozenset()


def test_unknown_case_is_not_found_for_the_filing_side(filer):
    with pytest.raises(NotFound):
        permissions.filing_case(uuid.uuid4(), filer)
