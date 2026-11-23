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


def test_seeding_the_orders_folder_twice_changes_nothing(settings):
    path = str(settings.BASE_DIR.parent / "data" / "seed" / "core" / "orders")
    out = StringIO()
    call_command("seed", path, "--strict", stdout=out)
    assert "created 0" in out.getvalue().splitlines()[-1]
    assert OrderItemType.objects.count() == 26


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
