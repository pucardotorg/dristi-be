"""The seeded catalogue and the app's own wiring (spec 0039 #3.11, #1.2)."""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.orders import handlers
from apps.orders.enums import Availability, TriggerPhase
from apps.orders.models import OrderItemCombinationRule, OrderItemType, OrderType

pytestmark = pytest.mark.django_db


def test_the_catalogue_is_seeded_by_the_session_fixture():
    assert OrderItemType.objects.count() == 26
    assert OrderItemCombinationRule.objects.count() == 5
    assert set(OrderType.objects.values_list("state_code", flat=True)) == {"KL", "GJ", "PH"}


CATALOGUE = (OrderItemType, OrderType, OrderItemCombinationRule)


def catalogue_snapshot():
    """Every catalogue row's field values, and each many-to-many's members by primary key."""
    snapshot = {}
    for model in CATALOGUE:
        fields = model._meta.concrete_fields
        many = [field.name for field in model._meta.many_to_many]
        for row in model.objects.prefetch_related(*many):
            values = {field.attname: field.value_from_object(row) for field in fields}
            for name in many:
                values[name] = sorted(str(member.pk) for member in getattr(row, name).all())
            snapshot[(model.__name__, row.pk)] = values
    return snapshot


def reseed(settings):
    path = str(settings.BASE_DIR.parent / "data" / "seed" / "core" / "orders")
    out = StringIO()
    call_command("seed", path, "--strict", stdout=out)
    return out.getvalue().splitlines()[-1]


def test_seeding_the_orders_folder_twice_changes_nothing(settings):
    before = catalogue_snapshot()
    assert "created 0" in reseed(settings)
    assert catalogue_snapshot() == before
    assert OrderItemType.objects.count() == 26


def test_reseeding_keeps_what_an_admin_changed(settings):
    seeded = catalogue_snapshot()
    item_type = OrderItemType.objects.get(code="COST")
    order_type = OrderType.objects.filter(state_code="GJ").first()
    item_type.label = "Edited item"
    item_type.save()
    order_type.label = "Edited type"
    order_type.save()
    for rule in OrderItemCombinationRule.objects.all():
        rule.item_types.remove(rule.item_types.first())
    edited = catalogue_snapshot()
    assert [key for key in seeded if seeded[key] != edited[key]]  # the edits took effect

    assert "created 0" in reseed(settings)

    assert catalogue_snapshot() == edited
    assert edited[("OrderItemType", item_type.pk)]["label"] == "Edited item"
    assert edited[("OrderType", order_type.pk)]["label"] == "Edited type"


def test_every_seeded_workflow_item_has_a_handler():
    missing = [
        item.code
        for item in OrderItemType.objects.filter(has_workflow=True)
        if handlers.get(item.code) is None
    ]
    assert missing == []


def test_each_state_has_exactly_one_normal_type():
    for state in ("KL", "GJ", "PH"):
        assert OrderType.objects.filter(state_code=state, code="NORMAL").count() == 1


def test_scheduling_items_run_first_and_case_closing_items_last():
    first = set(
        OrderItemType.objects.filter(trigger_phase=TriggerPhase.FIRST).values_list(
            "code", flat=True
        )
    )
    assert first == {"SCHEDULING_OF_HEARING_DATE", "RESCHEDULING_OF_HEARING_DATE"}
    closing = set(OrderItemType.objects.exclude(closes_case="").values_list("code", flat=True))
    assert closing <= set(
        OrderItemType.objects.filter(trigger_phase=TriggerPhase.LAST).values_list("code", flat=True)
    )


def test_contextual_items_have_no_category_and_name_their_target():
    for item in OrderItemType.objects.filter(availability=Availability.CONTEXTUAL):
        assert item.category == ""
        assert item.target_type == "APPLICATION"


def test_rule_membership_changes_are_kept_in_history():
    rule = OrderItemCombinationRule.objects.first()
    before = set(rule.item_types.values_list("pk", flat=True))
    rule.item_types.remove(rule.item_types.first())
    after = set(rule.item_types.values_list("pk", flat=True))
    assert before != after
    latest, previous = rule.history.all()[:2]
    assert {m.orderitemtype_id for m in latest.item_types.all()} == after
    assert {m.orderitemtype_id for m in previous.item_types.all()} == before
