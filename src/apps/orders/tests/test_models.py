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


def test_the_seeded_rules_name_their_items():
    rule = OrderItemCombinationRule.objects.get(code="ONE_HEARING_DATE_ITEM")
    assert {i.code for i in rule.item_types.all()} == {
        "SCHEDULING_OF_HEARING_DATE",
        "RESCHEDULING_OF_HEARING_DATE",
    }
    assert uuid and OrderType


@pytest.mark.parametrize("options", [7, "COURT", [], [1, 2], None])
def test_enum_options_must_be_a_nonempty_list_of_strings(options):
    schema = {"fields": [{"key": "k", "label": "L", "input": "ENUM", "options": options}]}
    assert field_schema.schema_errors(schema)


def test_enum_options_as_strings_are_valid():
    schema = {"fields": [{"key": "k", "label": "L", "input": "ENUM", "options": ["A", "B"]}]}
    assert field_schema.schema_errors(schema) == []


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
