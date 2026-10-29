"""Read models and read access (spec 0024 #7, #8.4, #10)."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.cases.models import Case, CaseStatus
from apps.scrutiny import permissions, selectors
from apps.scrutiny.enums import ResponseKind, RoundStage
from apps.scrutiny.services import rounds

from .factories import answer, code, draft_field, enter, make_case, open_round

pytestmark = pytest.mark.django_db


def list_rows(user, **kwargs):
    found = selectors.scrutiny_list(user, **kwargs)
    return found["counts"], selectors.scrutiny_rows(found["rounds"])


def send_back_and_resubmit(case, officer, filer, explain=True):
    flag = draft_field(case, officer, "CHQ-3[0]", note="Amount reads ₹50,25,000.")[0]
    rounds.send_back(case.pk, officer)
    answer(flag, filer, ResponseKind.EXPLAINED if explain else ResponseKind.CORRECTED)
    enter(case, CaseStatus.UNDER_SCRUTINY)
    return flag


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


def test_closed_row_follows_the_round_decision(officer_registerer, filer, establishment):
    registered = make_case(filer, establishment, filing_number="F/EST/2026/00007")
    rounds.register_at_scrutiny(registered.pk, officer_registerer)
    # The row follows the round's decision, not the case status.
    Case.objects.filter(pk=registered.pk).update(status=CaseStatus.UNDER_SCRUTINY)
    _, rows = list_rows(officer_registerer, tab="closed")
    assert [(row["stage"], row["reason"]) for row in rows] == [
        ("REGISTERED", f"CC/1/{timezone.now().year}")
    ]
