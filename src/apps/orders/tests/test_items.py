"""Order items (spec 0039 #6.1-#6.3): availability, combinations, defaults, completion."""

import uuid

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.api.errors import BusinessError
from apps.orders import field_schema
from apps.orders.enums import ItemSource, OrderStatus
from apps.orders.models import Order, OrderItem, OrderItemCombinationRule, OrderItemType
from apps.orders.services import drafting, items, lifecycle
from apps.orders.services.common import ProblemsError

from .factories import code, field, make_case

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
    assert reasons["RESCHEDULING_OF_HEARING_DATE"]["unavailable_reason"]["code"] == (
        "NO_HEARING_SCHEDULED"
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
    with pytest.raises(BusinessError) as excinfo:
        add(other, "MOVE_OUT_OF_LONG_PENDING_REGISTER", filler)
    assert (code(excinfo), field(excinfo)) == ("E14008", "item_type")


def test_a_retired_item_cannot_be_added(order, filler):
    OrderItemType.objects.filter(code="BAIL").update(is_active=False)
    with pytest.raises(BusinessError) as excinfo:
        add(order, "BAIL", filler)
    assert code(excinfo) == "E14008"


# -- combinations ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("JUDGEMENT", "DISMISS_CASE"),
        ("CASE_SETTLEMENT", "ABATE_CASE"),
        ("COGNIZANCE", "DISMISS_CASE"),
        ("COGNIZANCE", "COGNIZANCE"),
        ("DISMISS_CASE", "DISMISS_CASE"),
    ],
)
def test_the_catalogue_combination_rules_are_refused_with_their_message(
    order, filler, first, second
):
    add(order, first, filler)
    with pytest.raises(BusinessError) as excinfo:
        add(order, second, filler)
    assert code(excinfo) == "E14009"
    # The message is the configured rule's, with the two items' labels (ITM-07, #11.6).
    existing, adding = (OrderItemType.objects.get(code=c) for c in (first, second))
    rules = OrderItemCombinationRule.objects.filter(item_types=existing).filter(item_types=adding)
    configured = {r.message.format(adding=adding.label, existing=existing.label) for r in rules}
    assert field(excinfo) == "item_type"
    assert str(excinfo.value.detail["item_type"][0]) in configured


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
    for values, key in (
        ({"amount": "-3"}, "values.amount"),
        ({"paying_party": "NOBODY"}, "values.paying_party"),
        ({"unknown": "x"}, "values.unknown"),
    ):
        with pytest.raises(ValidationError) as excinfo:
            add(order, "COST", filler, values=values)
        assert excinfo.value.detail[key][0].code == "E14011", key


def test_a_deadline_must_be_a_date(order, filler):
    with pytest.raises(ValidationError) as excinfo:
        add(order, "MANDATORY_SUBMISSIONS", filler, values={"deadline": "not-a-date"})
    assert excinfo.value.detail["values.deadline"][0].code == "E14011"


def test_a_hearing_purpose_must_be_an_active_one(order):
    from apps.hearings.models import HearingPurpose

    HearingPurpose.objects.create(code="RETIRED", label="Retired", sequence=99, is_active=False)
    item_type = OrderItemType.objects.get(code="SCHEDULING_OF_HEARING_DATE")
    handler = items.handler_for(item_type)
    ctx = items.context_for(order, source="SYSTEM")

    def purpose_problems(purpose):
        values = {"hearing_date": "2030-01-01", "hearing_purpose": purpose}
        found = items.values_problems(order, item_type, values, handler, ctx)
        return [p for p in found if p.field == "values.hearing_purpose"]

    assert purpose_problems("ARGUMENTS") == []  # active: the control
    assert [p.code for p in purpose_problems("RETIRED")] == ["INVALID_PURPOSE"]


def test_a_person_chosen_must_be_in_the_case(order, filler):
    with pytest.raises(ValidationError) as excinfo:
        add(order, "ISSUE_OF_SUMMONS", filler, values={"party_names": [str(uuid.uuid4())]})
    assert excinfo.value.detail["values.party_names"][0].code == "E14011"


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
    with pytest.raises(ProblemsError) as excinfo:
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
    with pytest.raises(ProblemsError) as excinfo:
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


def test_participant_ids_compare_as_uuids(order):
    from apps.orders.services.items import _party_ids

    ids = _party_ids(order, ("ACCUSED",))
    chosen = next(iter(ids))
    assert field_schema.canonical_id(chosen.upper()) in ids
    field = {"key": "k", "label": "L", "input": "PARTIES"}
    assert field_schema.value_problem(field, [chosen, chosen.upper()])


def test_a_participant_id_in_capitals_is_one_of_the_case(order, filler):
    from apps.orders.services.items import _party_ids

    (accused,) = _party_ids(order, ("ACCUSED",))
    item = items.add(
        order.pk, "ISSUE_OF_SUMMONS", actor=filler, values={"party_names": [accused.upper()]}
    )
    assert item.pk


# -- read-only (RECORD) fields on update ----------------------------------------------


def _withdrawal(order, filler, **stored):
    """A ``WITHDRAWAL_OF_CASE`` item whose stored values are exactly ``stored``."""
    item = add(order, "WITHDRAWAL_OF_CASE", filler)
    OrderItem.objects.filter(pk=item.pk).update(values=stored)
    item.refresh_from_db()
    return item


def _read_only_error(excinfo, key):
    detail = excinfo.value.detail
    assert f"values.{key}" in detail
    assert detail[f"values.{key}"][0].code == "E14011"


def test_a_null_for_a_record_key_the_item_lacks_is_refused(order, filler):
    item = _withdrawal(order, filler)
    before = Order.objects.get(pk=order.pk).data_version
    with pytest.raises(ValidationError) as excinfo:
        items.update(order.pk, item.pk, {"application_number": None}, actor=filler)
    _read_only_error(excinfo, "application_number")
    item.refresh_from_db()
    assert "application_number" not in item.values
    assert Order.objects.get(pk=order.pk).data_version == before


def test_a_value_for_a_record_key_the_item_lacks_is_refused(order, filler):
    item = _withdrawal(order, filler)
    with pytest.raises(ValidationError) as excinfo:
        items.update(order.pk, item.pk, {"application_number": "A/9/2026"}, actor=filler)
    _read_only_error(excinfo, "application_number")


def test_changing_a_stored_record_value_is_refused(order, filler):
    item = _withdrawal(order, filler, application_number="A/1/2026")
    for typed in ("A/2/2026", None):
        with pytest.raises(ValidationError) as excinfo:
            items.update(order.pk, item.pk, {"application_number": typed}, actor=filler)
        _read_only_error(excinfo, "application_number")
    item.refresh_from_db()
    assert item.values == {"application_number": "A/1/2026"}


@pytest.mark.parametrize("stored", ["A/1/2026", None])
def test_an_equal_echo_of_a_stored_record_value_passes_unchanged(order, filler, stored):
    item = _withdrawal(order, filler, application_number=stored)
    items.update(order.pk, item.pk, {"application_number": stored}, actor=filler)
    item.refresh_from_db()
    assert item.values == {"application_number": stored}
    assert item.unconfirmed_fields == []


def test_leaving_out_a_stored_record_key_keeps_it(order, filler):
    item = _withdrawal(order, filler, application_number="A/1/2026")
    items.update(order.pk, item.pk, {}, actor=filler)
    item.refresh_from_db()
    assert item.values == {"application_number": "A/1/2026"}


def test_the_system_may_add_a_record_key(order, filler):
    item = _withdrawal(order, filler)
    items.update(
        order.pk,
        item.pk,
        {"application_number": "A/1/2026"},
        source=ItemSource.SYSTEM,
        actor=filler,
    )
    item.refresh_from_db()
    assert item.values == {"application_number": "A/1/2026"}


# -- party lookup ------------------------------------------------------------------------


class _NoChecks:
    def validate(self, ctx, values, complete=False):
        return []


def test_fields_with_the_same_roles_share_one_party_lookup(order, monkeypatch):
    from types import SimpleNamespace

    from apps.orders.services.items import _party_ids

    (accused,) = _party_ids(order, ("ACCUSED",))
    (complainant,) = _party_ids(order, ("COMPLAINANT",))
    calls = []

    def counting(order, roles):
        calls.append(roles)
        return _party_ids(order, roles)

    monkeypatch.setattr(items, "_party_ids", counting)
    item_type = SimpleNamespace(
        field_schema={
            "fields": [
                {"key": "a", "label": "A", "input": "PARTY", "party_types": ["ACCUSED"]},
                {"key": "b", "label": "B", "input": "PARTIES", "party_types": ["ACCUSED"]},
                {"key": "c", "label": "C", "input": "PARTY", "party_types": ["ACCUSED"]},
                {"key": "d", "label": "D", "input": "PARTY", "party_types": ["COMPLAINANT"]},
            ]
        }
    )
    values = {"a": accused, "b": [accused], "c": accused, "d": complainant}
    assert items.values_problems(order, item_type, values, _NoChecks(), None) == []
    assert calls == [("ACCUSED",), ("COMPLAINANT",)]


def test_a_shared_party_lookup_still_refuses_a_person_outside_the_roles(order):
    from types import SimpleNamespace

    from apps.orders.services.items import _party_ids

    (accused,) = _party_ids(order, ("ACCUSED",))
    (complainant,) = _party_ids(order, ("COMPLAINANT",))
    item_type = SimpleNamespace(
        field_schema={
            "fields": [
                {"key": "a", "label": "A", "input": "PARTY", "party_types": ["ACCUSED"]},
                {"key": "b", "label": "B", "input": "PARTY", "party_types": ["ACCUSED"]},
            ]
        }
    )
    problems = items.values_problems(
        order, item_type, {"a": accused, "b": complainant}, _NoChecks(), None
    )
    assert [(p.field, p.code) for p in problems] == [("values.b", "NOT_IN_CASE")]


# -- refusals and the reading layer on update -----------------------------------------


NOT_ON_CASE = "The application is not on this case."


class _RefusingTarget:
    """A handler that refuses the application an item names (as ``apps.applications`` will)."""

    def __init__(self, real):
        self.real = real

    def __getattr__(self, name):
        return getattr(self.real, name)

    def validate_target(self, ctx):
        from apps.orders.handlers.base import Problem

        return [Problem("target_id", "NOT_ON_CASE", NOT_ON_CASE)]


def test_an_unknown_item_code_is_not_available(order, filler):
    with pytest.raises(BusinessError) as excinfo:
        add(order, "NO_SUCH_ITEM", filler)
    assert code(excinfo) == "E14008" and field(excinfo) == "item_type"
    assert not order.items.exists()


def test_a_handler_refusing_the_application_refuses_the_item_on_its_target(
    order, filler, monkeypatch
):
    real = items.handler_for
    monkeypatch.setattr(items, "handler_for", lambda item_type: _RefusingTarget(real(item_type)))
    with pytest.raises(BusinessError) as excinfo:
        add(order, "ACCEPT_APPLICATION", filler, target_id=uuid.uuid4())
    assert code(excinfo) == "E14010" and field(excinfo) == "target_id"
    # The handler's own reason reaches the caller, not a generic message.
    assert str(excinfo.value.detail["target_id"][0]) == NOT_ON_CASE
    assert not order.items.exists()


def test_a_target_refused_later_stops_the_order_data_being_complete(order, filler, monkeypatch):
    add(order, "ACCEPT_APPLICATION", filler, target_id=uuid.uuid4())
    assert items.completion_problems(Order.objects.get(pk=order.pk)) == []
    real = items.handler_for
    monkeypatch.setattr(items, "handler_for", lambda item_type: _RefusingTarget(real(item_type)))
    assert items.completion_problems(Order.objects.get(pk=order.pk)) == [
        ("items[1].target_id", "The application is not on this case.")
    ]


def test_editing_an_item_not_on_the_order_is_not_found(order, filler):
    from rest_framework.exceptions import NotFound

    with pytest.raises(NotFound):
        items.update(order.pk, uuid.uuid4(), {"amount": "1.00"}, actor=filler)


def test_an_edit_with_a_bad_value_is_refused_and_keeps_the_stored_values(order, filler):
    item = add(order, "COST", filler, values={"amount": "5.00"})
    before = Order.objects.get(pk=order.pk).data_version
    with pytest.raises(ValidationError) as excinfo:
        items.update(order.pk, item.pk, {"amount": "-3"}, actor=filler)
    assert excinfo.value.detail["values.amount"][0].code == "E14011"
    item.refresh_from_db()
    assert item.values == {"amount": "5.00"}
    assert Order.objects.get(pk=order.pk).data_version == before


def test_a_reader_edit_leaves_the_changed_fields_to_confirm(order, filler):
    item = add(order, "COST", filler, values={"amount": "5.00"})
    assert (item.confirmed, item.unconfirmed_fields) == (True, [])
    items.update(
        order.pk, item.pk, {"amount": "6.00", "pay_by": "2026-12-01"}, source=ItemSource.READER
    )
    item.refresh_from_db()
    assert item.confirmed is False
    assert item.unconfirmed_fields == ["amount", "pay_by"]
    problems = items.item_problems(Order.objects.get(pk=order.pk), item)
    assert ("confirmed", "UNCONFIRMED") in [(p.field, p.code) for p in problems]


def test_a_confirmed_item_shows_only_its_own_problems(order, filler):
    item = add(order, "COST", filler, values=COST)
    assert items.item_problems(Order.objects.get(pk=order.pk), item) == []


def test_confirm_paid_needs_a_witness_batta_of_a_triggered_order(order, filler):
    from rest_framework.exceptions import NotFound

    cost = add(order, "COST", filler)
    batta = add(order, "WITNESS_BATTA", filler)
    with pytest.raises(NotFound):
        items.confirm_paid(order.pk, cost.pk, user=filler)
    with pytest.raises(NotFound):
        items.confirm_paid(order.pk, uuid.uuid4(), user=filler)
    with pytest.raises(BusinessError) as excinfo:
        items.confirm_paid(order.pk, batta.pk, user=filler)
    assert code(excinfo) == "E14001"
