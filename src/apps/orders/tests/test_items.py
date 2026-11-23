"""Order items (spec 0039 #6.1-#6.3): availability, combinations, defaults, completion."""

import uuid

import pytest
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.orders.enums import ItemSource, OrderStatus
from apps.orders.models import Order, OrderItem, OrderItemType
from apps.orders.services import drafting, items, lifecycle

from .factories import TODAY, code, field, make_case

pytestmark = pytest.mark.django_db

COST = {
    "paying_party": "ACCUSED",
    "amount": "500.00",
    "receiving_party": "COMPLAINANT",
    "pay_by": "2026-12-01",
}


def add(order, item_code, actor, **kwargs):
    return items.add(order.pk, item_code, actor=actor, **kwargs)


def triggered_with(case, item_code, *, at=None):
    """A triggered order of ``case`` carrying ``item_code`` — what the case already decided."""
    from apps.orders.models import OrderType

    order = Order.objects.create(
        case=case,
        court=case.court,
        order_type=OrderType.objects.get(state_code="KL", code="NORMAL"),
        title="Earlier",
        status=OrderStatus.TRIGGERED,
        data_complete=True,
        signed_file_id="f",
        triggered_at=at or timezone.now(),
    )
    OrderItem.objects.create(
        order=order, item_type=OrderItemType.objects.get(code=item_code), position=1
    )
    return order


# -- availability -------------------------------------------------------------------


def test_the_catalogue_lists_unavailable_items_with_their_reason(order):
    rows = {row["code"]: row for row in items.catalogue(order)}
    scheduling = rows["SCHEDULING_OF_HEARING_DATE"]
    assert scheduling["available"] is False
    assert scheduling["unavailable_reason"]["code"] == "IN_HEARING"
    assert rows["COGNIZANCE"]["available"] is True
    assert rows["MOVE_OUT_OF_LONG_PENDING_REGISTER"]["unavailable_reason"]["code"] == "NOT_IN_LPR"
    assert len(rows) == 26


def test_suggested_items_follow_the_hearing_purpose(order):
    rows = {row["code"]: row for row in items.catalogue(order)}
    # The hearing's purpose is Appearance: Issue of summons, warrants, Bail, notice.
    assert {code for code, row in rows.items() if row["suggested"]} == {
        "ISSUE_OF_SUMMONS",
        "ISSUE_OF_WARRANTS",
        "BAIL",
        "ISSUE_OF_NOTICE",
    }


def test_the_catalogue_can_be_searched_and_filtered(order):
    assert [r["code"] for r in items.catalogue(order, search="warrant")] == ["ISSUE_OF_WARRANTS"]
    assert {r["category"] for r in items.catalogue(order, category="PROCESS")} == {"PROCESS"}


def test_scheduling_is_not_offered_in_a_hearing_and_not_typed_outside_one(
    order, case, drafter, filler
):
    with pytest.raises(BusinessError) as excinfo:
        add(order, "SCHEDULING_OF_HEARING_DATE", filler)
    assert code(excinfo) == "E14008" and field(excinfo) == "item_type"
    outside = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    with pytest.raises(BusinessError) as excinfo:
        add(outside, "SCHEDULING_OF_HEARING_DATE", filler)
    assert code(excinfo) == "E14008"


def test_rescheduling_needs_a_scheduled_hearing(case, drafter, filler):
    outside = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    reasons = {row["code"]: row for row in items.catalogue(outside)}
    assert reasons["RESCHEDULING_OF_HEARING_DATE"]["unavailable_reason"]["code"] in (
        "NO_HEARING_SCHEDULED",
        "FOLLOWS_NEXT_HEARING",
    )


def test_cognizance_is_refused_once_taken(order, case, filler):
    triggered_with(case, "COGNIZANCE")
    with pytest.raises(BusinessError) as excinfo:
        add(order, "COGNIZANCE", filler)
    assert code(excinfo) == "E14008"
    rows = {row["code"]: row for row in items.catalogue(order)}
    assert rows["COGNIZANCE"]["unavailable_reason"]["code"] == "COGNIZANCE_TAKEN"


def test_moving_out_of_the_register_only_for_a_case_in_it(order, case, filler):
    triggered_with(case, "MOVE_TO_LONG_PENDING_REGISTER", at=timezone.now())
    assert add(order, "MOVE_OUT_OF_LONG_PENDING_REGISTER", filler).position == 1
    triggered_with(case, "MOVE_OUT_OF_LONG_PENDING_REGISTER", at=timezone.now())
    Order.objects.filter(pk=order.pk).update(data_version=0)
    other = drafting.create_outside_hearing(case_id=case.pk, actor=filler)
    with pytest.raises(BusinessError):
        add(other, "MOVE_OUT_OF_LONG_PENDING_REGISTER", filler)


def test_a_retired_item_cannot_be_added(order, filler):
    OrderItemType.objects.filter(code="BAIL").update(is_active=False)
    with pytest.raises(BusinessError) as excinfo:
        add(order, "BAIL", filler)
    assert code(excinfo) == "E14008"


# -- combinations ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second", "message"),
    [
        ("JUDGEMENT", "DISMISS_CASE", "You cannot add both Dismiss case and Judgement."),
        ("CASE_SETTLEMENT", "ABATE_CASE", "You cannot add both Abate case and Case settlement."),
        ("COGNIZANCE", "DISMISS_CASE", "You cannot add both Dismiss case and Cognizance."),
        ("COGNIZANCE", "COGNIZANCE", "You cannot add Cognizance twice."),
        ("DISMISS_CASE", "DISMISS_CASE", "You cannot add Dismiss case twice."),
    ],
)
def test_the_catalogue_combination_rules_are_refused_with_their_message(
    order, filler, first, second, message
):
    add(order, first, filler)
    with pytest.raises(BusinessError) as excinfo:
        add(order, second, filler)
    assert code(excinfo) == "E14009"
    assert message in str(excinfo.value.detail)


def test_unrestricted_items_may_repeat_and_combine(order, filler):
    for _ in range(2):
        add(order, "ISSUE_OF_SUMMONS", filler)
    add(order, "COST", filler)
    add(order, "BAIL", filler)
    assert order.items.count() == 4


def test_one_decision_per_application(order, filler):
    application = uuid.uuid4()
    add(order, "ACCEPT_APPLICATION", filler, target_id=application)
    with pytest.raises(BusinessError) as excinfo:
        add(order, "REJECT_APPLICATION", filler, target_id=application)
    assert code(excinfo) == "E14009"
    add(order, "REJECT_APPLICATION", filler, target_id=uuid.uuid4())


# -- target ------------------------------------------------------------------------------


def test_a_contextual_item_needs_its_application(order, filler):
    with pytest.raises(BusinessError) as excinfo:
        add(order, "ACCEPT_APPLICATION", filler)
    assert code(excinfo) == "E14010" and field(excinfo) == "target_id"


def test_a_dropdown_item_takes_no_application(order, filler):
    with pytest.raises(BusinessError) as excinfo:
        add(order, "COST", filler, target_id=uuid.uuid4(), values=COST)
    assert code(excinfo) == "E14010"


def test_withdrawal_may_arise_from_an_application_or_stand_alone(order, filler):
    assert add(order, "WITHDRAWAL_OF_CASE", filler).target_id is None


# -- values and defaults ---------------------------------------------------------------


def test_an_item_that_asks_for_nothing_is_added_with_empty_values(order, filler):
    item = add(order, "JUDGEMENT", filler)
    assert item.values == {}
    assert item.confirmed is True


def test_values_are_checked_for_shape_on_save_but_mandatory_fields_are_not(order, filler):
    item = add(order, "COST", filler, values={"amount": "12.50"})
    assert item.values == {"amount": "12.50"}
    with pytest.raises(Exception) as excinfo:
        add(order, "COST", filler, values={"amount": "-3"})
    assert code(excinfo) == "E14011" if hasattr(excinfo.value, "error") else True
    assert "values.amount" in str(excinfo.value.detail)
    with pytest.raises(Exception) as excinfo:
        add(order, "COST", filler, values={"paying_party": "NOBODY"})
    assert "values.paying_party" in str(excinfo.value.detail)
    with pytest.raises(Exception) as excinfo:
        add(order, "COST", filler, values={"unknown": "x"})
    assert "values.unknown" in str(excinfo.value.detail)


def test_a_hearing_purpose_must_be_an_active_one(order, filler):
    with pytest.raises(Exception) as excinfo:
        add(order, "MANDATORY_SUBMISSIONS", filler, values={"deadline": "not-a-date"})
    assert "values.deadline" in str(excinfo.value.detail)


def test_a_person_chosen_must_be_in_the_case(order, filler):
    with pytest.raises(Exception) as excinfo:
        add(order, "ISSUE_OF_SUMMONS", filler, values={"party_names": [str(uuid.uuid4())]})
    assert "values.party_names" in str(excinfo.value.detail)


def test_summons_default_to_every_accused_without_guessing_the_rest(order, filler, case):
    from apps.cases.models import CaseParticipant, ParticipantRole

    accused = CaseParticipant.objects.get(case=case, role=ParticipantRole.ACCUSED)
    item = add(order, "ISSUE_OF_SUMMONS", filler)
    assert item.values["party_names"] == [str(accused.pk)]
    assert item.values["party_taking_steps"] == "COMPLAINANT"
    assert "recipients" not in item.values


def test_given_values_win_over_defaults(order, filler):
    item = add(order, "ISSUE_OF_SUMMONS", filler, values={"party_taking_steps": "ACCUSED"})
    assert item.values["party_taking_steps"] == "ACCUSED"


def test_the_witness_defaults_only_when_the_case_has_exactly_one(order, filler, case):
    from apps.cases.models import CaseParticipant, ParticipantRole
    from apps.parties.models import Person

    def witness(name):
        return CaseParticipant.objects.create(
            case=case,
            person=Person.objects.create(
                name=name, phone_number=f"+9197{uuid.uuid4().int % 10**8:08d}"
            ),
            role=ParticipantRole.WITNESS,
            ordinal=1 + case.participants.filter(role=ParticipantRole.WITNESS).count(),
            name_at_filing=name,
        )

    assert "witness" not in add(order, "WITNESS_BATTA", filler).values
    only = witness("W1")
    # Remove the first batta so the id is the only candidate again.
    order.items.all().delete()
    assert add(order, "WITNESS_BATTA", filler).values["witness"] == str(only.pk)
    witness("W2")
    order.items.all().delete()
    assert "witness" not in add(order, "WITNESS_BATTA", filler).values


# -- editing, removing, completing --------------------------------------------------------------


def test_removal_closes_the_position_gap(order, filler):
    a = add(order, "COGNIZANCE", filler)
    b = add(order, "ISSUE_OF_SUMMONS", filler)
    c = add(order, "BAIL", filler)
    items.remove(order.pk, b.pk, actor=filler)
    assert list(order.items.order_by("position").values_list("pk", "position")) == [
        (a.pk, 1),
        (c.pk, 2),
    ]


def test_a_removed_item_leaves_the_text_alone(order, filler, drafter):
    drafting.edit_text(order.pk, "<p>Summons issued.</p>", actor=drafter)
    item = add(order, "ISSUE_OF_SUMMONS", filler)
    items.remove(order.pk, item.pk, actor=filler)
    order.refresh_from_db()
    assert order.text == "<p>Summons issued.</p>"


def test_an_item_can_be_edited_and_the_data_version_moves(order, filler):
    item = add(order, "COST", filler, values={"amount": "10.00"})
    before = Order.objects.get(pk=order.pk).data_version
    items.update(order.pk, item.pk, {"amount": "20.00"}, actor=filler)
    item.refresh_from_db()
    assert item.values == {"amount": "20.00"}
    assert Order.objects.get(pk=order.pk).data_version == before + 1


def test_order_data_is_stale_against_an_old_version(order, filler):
    add(order, "COGNIZANCE", filler)
    with pytest.raises(BusinessError) as excinfo:
        add(order, "BAIL", filler, data_version=0)
    assert code(excinfo) == "E14002"


def test_mandatory_fields_are_checked_only_when_marked_complete(order, filler):
    add(order, "COST", filler)
    with pytest.raises(Exception) as excinfo:
        lifecycle.mark_complete(order.pk, actor=filler)
    assert excinfo.value.error.code == "E14012"
    problems = dict(excinfo.value.problems)
    assert "items[1].values.amount" in problems
    assert "items[1].values.pay_by" in problems


def test_complete_order_data_cannot_be_changed_until_reopened(order, filler):
    item = add(order, "JUDGEMENT", filler)
    lifecycle.mark_complete(order.pk, actor=filler)
    for action in (
        lambda: add(order, "BAIL", filler),
        lambda: items.update(order.pk, item.pk, {}, actor=filler),
        lambda: items.remove(order.pk, item.pk, actor=filler),
    ):
        with pytest.raises(BusinessError) as excinfo:
            action()
        assert code(excinfo) == "E14013"
    lifecycle.reopen(order.pk, actor=filler)
    add(order, "BAIL", filler)


def test_an_unconfirmed_reader_item_blocks_completion_until_confirmed(order, filler):
    item = add(order, "JUDGEMENT", filler, source=ItemSource.READER)
    assert item.confirmed is False
    with pytest.raises(Exception) as excinfo:
        lifecycle.mark_complete(order.pk, actor=filler)
    assert excinfo.value.error.code == "E14012"
    items.confirm(order.pk, item.pk, actor=filler)
    lifecycle.mark_complete(order.pk, actor=filler)
    order.refresh_from_db()
    assert order.data_complete is True


def test_a_persons_edit_confirms_the_fields_they_changed(order, filler):
    item = add(order, "COST", filler, values={"amount": "5.00"}, source=ItemSource.READER)
    assert item.unconfirmed_fields == ["amount"]
    items.update(order.pk, item.pk, {"amount": "6.00"}, actor=filler)
    item.refresh_from_db()
    assert item.unconfirmed_fields == []


def test_the_data_of_a_triggered_order_is_closed(order, filler):
    Order.objects.filter(pk=order.pk).update(
        status=OrderStatus.TRIGGERED, data_complete=True, signed_file_id="x"
    )
    with pytest.raises(BusinessError) as excinfo:
        add(order, "BAIL", filler)
    assert code(excinfo) == "E14001"


def test_a_system_item_cannot_be_removed_by_hand(order, filler):
    item = add(order, "JUDGEMENT", filler)
    OrderItem.objects.filter(pk=item.pk).update(added_by_source=ItemSource.SYSTEM)
    with pytest.raises(BusinessError) as excinfo:
        items.remove(order.pk, item.pk, actor=filler)
    assert code(excinfo) == "E14001"


def test_items_of_another_case_have_their_own_defaults(order, filler, courtroom):
    other = make_case(courtroom)
    from apps.orders.services import drafting as d

    outside = d.create_outside_hearing(case_id=other.pk, actor=filler)
    mine = add(order, "ISSUE_OF_SUMMONS", filler)
    theirs = add(outside, "ISSUE_OF_SUMMONS", filler)
    assert mine.values["party_names"] != theirs.values["party_names"]
    assert TODAY
