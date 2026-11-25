"""Model constraints and the order's invariants (spec 0039 #3)."""

import uuid

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.orders import field_schema
from apps.orders.enums import NextHearingState, OrderStatus
from apps.orders.models import (
    Order,
    OrderItem,
    OrderItemCombinationRule,
    OrderItemType,
    OrderNumberCounter,
    OrderRoznama,
    OrderShortcut,
    OrderType,
    OrderWorkflowRun,
)

pytestmark = pytest.mark.django_db


def make(case, **overrides):
    values = {
        "case": case,
        "court": case.court,
        "order_type": OrderType.objects.get(state_code="KL", code="NORMAL"),
        "title": "Order",
    }
    values.update(overrides)
    return Order.objects.create(**values)


def rejected(**kwargs):
    with pytest.raises(IntegrityError), transaction.atomic():
        make(**kwargs)


def test_one_live_order_per_hearing_but_a_discarded_one_does_not_count(hearing, case):
    first = make(case, hearing_id=hearing.pk)
    rejected(case=case, hearing_id=hearing.pk)
    Order.objects.filter(pk=first.pk).update(status=OrderStatus.DISCARDED)
    assert make(case, hearing_id=hearing.pk).pk != first.pk


def test_outside_a_hearing_any_number_of_drafts(case):
    make(case)
    make(case)
    assert Order.objects.filter(case=case, hearing__isnull=True).count() == 2


def test_a_number_is_unique_when_set(case):
    make(case, number="C/ORD/1/2026")
    rejected(case=case, number="C/ORD/1/2026")
    make(case)
    make(case)  # empty numbers never collide


def test_a_signed_order_has_a_file_and_a_triggered_order_complete_data(case):
    rejected(case=case, status=OrderStatus.SIGNED)
    rejected(case=case, status=OrderStatus.TRIGGERED, signed_file_id="f", data_complete=False)
    make(case, status=OrderStatus.TRIGGERED, signed_file_id="f", data_complete=True)


@pytest.mark.parametrize(
    "fields",
    [
        {"next_hearing_state": NextHearingState.LISTED},
        {"next_hearing_state": NextHearingState.LISTED, "next_hearing_date": timezone.now().date()},
        {"next_hearing_state": NextHearingState.UNSET, "next_hearing_purpose": "APPEARANCE"},
        {
            "next_hearing_state": NextHearingState.NOT_LISTED_AGAIN,
            "next_hearing_date": timezone.now().date(),
        },
    ],
)
def test_a_next_hearing_is_a_date_and_a_purpose_together_or_neither(case, fields):
    rejected(case=case, **fields)


def test_items_have_one_position_each(case):
    order = make(case)
    cost = OrderItemType.objects.get(code="COST")
    OrderItem.objects.create(order=order, item_type=cost, position=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderItem.objects.create(order=order, item_type=cost, position=1)


def test_a_run_has_a_unique_sequence_and_a_counter_a_unique_scope(case):
    order = make(case)
    OrderWorkflowRun.objects.create(order=order, step="HEARING", sequence=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderWorkflowRun.objects.create(order=order, step="STAGE", sequence=1)
    OrderNumberCounter.objects.create(court=case.court, series="ORDER", year=2026)
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderNumberCounter.objects.create(court=case.court, series="ORDER", year=2026)


def test_an_order_has_at_most_one_roznama(case):
    order = make(case)
    OrderRoznama.objects.create(order=order)
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderRoznama.objects.create(order=order)


def test_a_signed_roznama_has_a_file(case):
    with pytest.raises(IntegrityError), transaction.atomic():
        OrderRoznama.objects.create(order=make(case), status="SIGNED")


def test_every_change_to_an_order_is_in_its_history(case, staff):
    order = make(case)
    order.title = "Changed"
    order._history_user = staff
    order.save()
    assert order.history.count() == 2
    assert order.history.first().history_user == staff


def test_an_order_is_never_deleted_while_it_has_runs(case):
    order = make(case)
    OrderWorkflowRun.objects.create(order=order, step="HEARING", sequence=1)
    with pytest.raises(ProtectedError):
        order.delete()


# -- catalogue validation ---------------------------------------------------------------


def test_a_field_schema_must_be_valid():
    item = OrderItemType.objects.get(code="COST")
    for bad in (
        {"fields": "nope"},
        {"fields": [{"key": "Bad Key", "label": "x", "input": "TEXT"}]},
        {"fields": [{"key": "a", "label": "x", "input": "WHAT"}]},
        {"fields": [{"key": "a", "label": "x", "input": "ENUM"}]},
        {
            "fields": [
                {"key": "a", "label": "x", "input": "TEXT"},
                {"key": "a", "label": "y", "input": "TEXT"},
            ]
        },
        {"other": []},
    ):
        item.field_schema = bad
        with pytest.raises(ValidationError) as excinfo:
            item.full_clean()
        assert "field_schema" in excinfo.value.message_dict


def test_a_contextual_item_names_its_target_and_has_no_category():
    item = OrderItemType(
        code="X_ITEM", label="X", availability="CONTEXTUAL", field_schema={"fields": []}
    )
    with pytest.raises(ValidationError) as excinfo:
        item.full_clean()
    assert "target_type" in excinfo.value.message_dict


def test_a_type_without_a_separate_entry_signs_none(case):
    order_type = OrderType.objects.get(state_code="GJ", code="ROZNAMA")
    order_type.signs_diary_entry = True
    with pytest.raises(ValidationError):
        order_type.full_clean()


def test_a_type_without_a_separate_entry_is_not_edited_in_the_a_diary():
    order_type = OrderType.objects.get(state_code="GJ", code="ROZNAMA")
    order_type.signs_diary_entry = False
    order_type.diary_entry_in_a_diary = True
    with pytest.raises(ValidationError) as excinfo:
        order_type.full_clean()
    assert "diary_entry_in_a_diary" in excinfo.value.message_dict


def test_the_seeded_rules_name_their_items():
    rule = OrderItemCombinationRule.objects.get(code="ONE_HEARING_DATE_ITEM")
    assert {i.code for i in rule.item_types.all()} == {
        "SCHEDULING_OF_HEARING_DATE",
        "RESCHEDULING_OF_HEARING_DATE",
    }
    assert uuid and OrderType


@pytest.mark.parametrize("options", [7, "COURT", [], [1, 2], None, [""], ["A", ""]])
def test_enum_options_must_be_a_nonempty_list_of_strings(options):
    schema = {"fields": [{"key": "k", "label": "L", "input": "ENUM", "options": options}]}
    assert field_schema.schema_errors(schema)


def test_enum_options_as_strings_are_valid():
    schema = {"fields": [{"key": "k", "label": "L", "input": "ENUM", "options": ["A", "B"]}]}
    assert field_schema.schema_errors(schema) == []


@pytest.mark.parametrize("value", ["20191204", "2019-W49-3", "2019-02-30", "2019-12-4", 20191204])
def test_a_date_value_must_be_yyyy_mm_dd(value):
    field = {"key": "k", "label": "When", "input": "DATE"}
    assert field_schema.value_problem(field, value) is not None


def test_a_valid_date_value_is_accepted():
    field = {"key": "k", "label": "When", "input": "DATE"}
    assert field_schema.value_problem(field, "2019-12-04") is None


@pytest.mark.parametrize("channels", [[None], [1], "SMS"])
def test_process_recipient_channels_must_be_strings(channels):
    field = {"key": "k", "label": "To", "input": "PROCESS_RECIPIENTS"}
    recipient = {"party_id": "6f9619ff-8b86-d011-b42d-00cf4fc964ff", "channels": channels}
    assert field_schema.value_problem(field, [recipient]) is not None
    assert field_schema.value_problem(field, [{**recipient, "channels": ["SMS"]}]) is None


@pytest.mark.parametrize("label", [["Notes"], 7, "", "  ", None])
def test_label_must_be_a_nonempty_string(label):
    schema = {"fields": [{"key": "k", "label": label, "input": "TEXT"}]}
    assert field_schema.schema_errors(schema)


@pytest.mark.parametrize("party_types", [7, "ACCUSED", [1], {"a": 1}, None])
def test_party_types_must_be_a_list_of_strings(party_types):
    schema = {"fields": [{"key": "k", "label": "L", "input": "PARTY", "party_types": party_types}]}
    assert field_schema.schema_errors(schema)


@pytest.mark.parametrize("extra", [{}, {"party_types": []}, {"party_types": ["ACCUSED"]}])
def test_party_types_omitted_or_listed_is_valid(extra):
    schema = {"fields": [{"key": "k", "label": "L", "input": "PARTY", **extra}]}
    assert field_schema.schema_errors(schema) == []


@pytest.mark.parametrize("value", [[{}], [1], ["NOPE"], "HEARING", [["HEARING"]]])
def test_preselect_from_malformed_is_a_field_error(value):
    order_type = OrderType.objects.first()
    order_type.preselect_from = value
    with pytest.raises(ValidationError) as excinfo:
        order_type.clean()
    assert "preselect_from" in excinfo.value.message_dict


@pytest.mark.parametrize("value", [[], ["HEARING"], ["HEARING", "APPLICATION_ONBOARDING"]])
def test_preselect_from_known_screens_is_valid(value):
    order_type = OrderType.objects.first()
    order_type.preselect_from = value
    order_type.clean()


def test_contextual_and_both_items_must_target_an_application():
    for availability in ("CONTEXTUAL", "BOTH"):
        item = OrderItemType.objects.filter(availability=availability).first()
        assert item is not None and item.target_type == "APPLICATION"
        item.clean()
        item.target_type = "HEARING"
        with pytest.raises(ValidationError) as excinfo:
            item.clean()
        assert "target_type" in excinfo.value.message_dict
        item.target_type = ""
        with pytest.raises(ValidationError):
            item.clean()


def test_every_seeded_item_passes_its_own_clean():
    for item in OrderItemType.objects.all():
        item.clean()


@pytest.mark.parametrize(
    "message",
    [
        "Cannot combine {adding} with {exsting}.",
        "Cannot combine {adding} with {}.",
        "Cannot combine {0}.",
        "Cannot combine {adding.x}.",
        "Cannot combine {adding",
        "Cannot combine adding}",
        "{adding:{foo}}",
    ],
)
def test_combination_rule_bad_placeholders_are_rejected(message):
    with pytest.raises(ValidationError) as excinfo:
        OrderItemCombinationRule(code="X", kind="NO_REPEAT", message=message).clean()
    assert "message" in excinfo.value.message_dict


@pytest.mark.parametrize(
    "message",
    ["Not allowed.", "Cannot combine {adding} with {existing}.", "{existing} then {adding}"],
)
def test_combination_rule_literal_and_documented_placeholders_are_valid(message):
    OrderItemCombinationRule(code="X", kind="NO_REPEAT", message=message).clean()


def test_seeded_combination_rules_pass_their_own_clean():
    for rule in OrderItemCombinationRule.objects.all():
        rule.clean()


@pytest.mark.parametrize(
    ("message", "valid"),
    [
        ("{adding} cannot be added to {existing}", True),
        ("Literal {{braces}} and {adding}", True),
        ("No placeholders at all", True),
        ("{adding:{existing}}", False),
        ("{adding:>10}", False),
        ("{adding!r}", False),
        ("{adding.x}", False),
        ("{other}", False),
        ("{adding", False),
    ],
)
def test_rule_message_placeholders_are_plain(message, valid):
    rule = OrderItemCombinationRule(code="X", kind="EXCLUSIVE", message=message)
    if valid:
        rule.clean()
    else:
        with pytest.raises(ValidationError):
            rule.clean()


def test_a_type_with_a_separate_entry_may_be_edited_in_the_a_diary():
    order_type = OrderType.objects.get(state_code="KL", code="NORMAL")
    assert order_type.separate_diary_entry and order_type.diary_entry_in_a_diary
    order_type.full_clean()


@pytest.mark.parametrize("state_code, type_code", [("KL", "NORMAL"), ("GJ", "ROZNAMA")])
def test_turning_off_the_separate_entry_of_an_a_diary_type_is_refused(state_code, type_code):
    order_type = OrderType.objects.get(state_code=state_code, code=type_code)
    order_type.separate_diary_entry = False
    order_type.signs_diary_entry = False
    order_type.diary_entry_in_a_diary = True
    with pytest.raises(ValidationError) as excinfo:
        order_type.full_clean()
    assert set(excinfo.value.message_dict) == {"diary_entry_in_a_diary"}


def test_every_seeded_order_type_is_valid():
    for order_type in OrderType.objects.all():
        order_type.full_clean()


def test_an_item_type_code_is_upper_case_and_a_contextual_item_has_no_category():
    item = OrderItemType(
        code="bad code",
        label="X",
        availability="CONTEXTUAL",
        target_type="APPLICATION",
        category="PROCESS",
        field_schema={"fields": []},
    )
    with pytest.raises(ValidationError) as excinfo:
        item.clean()
    assert set(excinfo.value.message_dict) == {"code", "category"}


def test_models_name_themselves_by_what_admins_look_for():
    order_id, case_id = uuid.uuid4(), uuid.uuid4()
    assert str(OrderItemType(code="COST")) == "COST"
    assert str(OrderItemCombinationRule(code="ONE_HEARING_DATE_ITEM")) == "ONE_HEARING_DATE_ITEM"
    assert str(Order(title="Order", case_id=case_id)) == f"Order ({case_id})"
    assert str(OrderItem(item_type_id=7, position=2)) == "7 #2"
    assert str(OrderShortcut(name="adjourn")) == "adjourn"
    run = OrderWorkflowRun(order_id=order_id, sequence=1, step="STAGE", status="PENDING")
    assert str(run) == f"{order_id} #1 STAGE PENDING"


@pytest.mark.parametrize(
    ("fields", "problem"),
    [
        (["not an object"], "fields[0] must be an object."),
        ([{"key": "k", "label": "L", "input": "TEXT", "extra": 1}], "has unknown keys: extra"),
        ([{"key": "k", "label": "L", "input": "MASTER"}], "master is required"),
        ([{"key": "k", "label": "L", "input": "TEXT", "mandatory": "yes"}], "true or false"),
    ],
)
def test_a_field_schema_names_each_malformed_field(fields, problem):
    errors = field_schema.schema_errors({"fields": fields})
    assert any(problem in error for error in errors), errors


@pytest.mark.parametrize(
    ("field", "value", "valid"),
    [
        ({"input": "TEXT"}, "fine", True),
        ({"input": "TEXT"}, 7, False),
        ({"input": "TEXT"}, "x" * (field_schema.MAX_TEXT + 1), False),
        ({"input": "AMOUNT"}, "250.50", True),
        ({"input": "AMOUNT"}, "250.505", False),
        ({"input": "ENUM", "options": ["A", "B"]}, "A", True),
        ({"input": "MASTER"}, "COURT_FEE", True),
        ({"input": "MASTER"}, "not a code!", False),
        ({"input": "HEARING_PURPOSE"}, 12, False),
        ({"input": "PARTY"}, "6f9619ff-8b86-d011-b42d-00cf4fc964ff", True),
        ({"input": "PARTY"}, "someone", False),
        ({"input": "PARTY"}, ["6f9619ff-8b86-d011-b42d-00cf4fc964ff"], False),
    ],
)
def test_a_value_has_the_shape_its_input_asks_for(field, value, valid):
    problem = field_schema.value_problem({"key": "k", "label": "L", **field}, value)
    assert (problem is None) is valid, problem


def test_a_value_outside_the_options_names_them():
    field = {"key": "k", "label": "Side", "input": "ENUM", "options": ["A", "B"]}
    assert field_schema.value_problem(field, "C") == ("NOT_AN_OPTION", "Side must be one of A, B.")
