"""The seeded catalogue and the app's own wiring (spec 0039 #3.11, #1.2)."""

import logging
import uuid
from io import StringIO

import pytest
from django.core.management import call_command

from apps.hearings.enums import HearingRole
from apps.orders import handlers, ports
from apps.orders.enums import Availability, OrderRole, TriggerPhase
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


# -- the stand-ins for modules not built yet (ports) ------------------------------------

# The real stand-ins, read before the autouse ``record_ports`` fixture replaces them.
REAL_PORTS = {
    name: getattr(ports, name)
    for name in (
        "open_task",
        "complete_task",
        "expire_task",
        "open_item_task",
        "complete_item_task",
        "complete_case_task",
        "dispatch_stage_event",
        "record_outcome",
    )
}


def test_court_roles_count_only_at_the_establishments_courtrooms(
    settings, courtroom, foreign_court
):
    from django.contrib.auth.models import AnonymousUser

    from .factories import make_user

    drafter = make_user(OrderRole.ORDER_DRAFTER, HearingRole.HEARING_CONTROLLER)
    assert ports.court_roles(drafter, courtroom.pk) == {OrderRole.ORDER_DRAFTER}
    assert ports.court_roles(drafter, foreign_court.pk) == frozenset()
    assert ports.court_roles(drafter, None) == frozenset()
    assert ports.court_roles(AnonymousUser(), courtroom.pk) == frozenset()
    settings.SCRUTINY_ESTABLISHMENT_ID = ""
    assert ports.court_roles(drafter, courtroom.pk) == frozenset()


def test_holding_a_role_anywhere_needs_the_establishment_and_the_role(settings, establishment):
    from django.contrib.auth.models import AnonymousUser

    from .factories import make_user

    signer = make_user(OrderRole.ORDER_SIGNER)
    assert ports.holds_role_anywhere(signer, OrderRole.ORDER_SIGNER)
    assert not ports.holds_role_anywhere(signer, OrderRole.ORDER_DRAFTER)
    assert not ports.holds_role_anywhere(AnonymousUser())
    settings.SCRUTINY_ESTABLISHMENT_ID = ""
    assert not ports.holds_role_anywhere(signer, OrderRole.ORDER_SIGNER)


def test_the_task_and_outcome_stand_ins_only_log(caplog):
    order_id, item_id, case_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with caplog.at_level(logging.INFO, logger="apps.orders.ports"):
        REAL_PORTS["open_task"](order_id, "sign_order", title="Sign the order")
        REAL_PORTS["complete_task"](order_id, "sign_order")
        REAL_PORTS["expire_task"](order_id, "sign_order")
        REAL_PORTS["complete_item_task"](item_id, "pay_cost")
        REAL_PORTS["complete_case_task"](case_id, "take_cognizance")
        REAL_PORTS["record_outcome"](case_id, "DISMISSED", order_id)
    events = [record.getMessage().split()[0] for record in caplog.records]
    assert events == [
        "event=ORDER_TASK_OPENED",
        "event=ORDER_TASK_COMPLETED",
        "event=ORDER_TASK_EXPIRED",
        "event=ORDER_ITEM_TASK_COMPLETED",
        "event=CASE_TASK_COMPLETED",
        "event=CASE_OUTCOME",
    ]


def test_an_item_task_returns_the_reference_the_run_records():
    order_id, item_id = uuid.uuid4(), uuid.uuid4()
    reference = REAL_PORTS["open_item_task"](order_id, item_id, "pay_cost", side="ACCUSED")
    assert reference == f"ORDER_ITEM:{item_id}:pay_cost"


def test_a_stage_event_is_sent_as_a_signal_for_its_receivers():
    received = []

    def receiver(sender, **kwargs):
        received.append(kwargs)

    ports.case_stage_event.connect(receiver)
    try:
        case_id = uuid.uuid4()
        REAL_PORTS["dispatch_stage_event"](case_id, "COGNIZANCE_TAKEN", {"idempotency_key": "k"})
    finally:
        ports.case_stage_event.disconnect(receiver)
    assert len(received) == 1
    assert (received[0]["case_id"], received[0]["event"], received[0]["context"]) == (
        case_id,
        "COGNIZANCE_TAKEN",
        {"idempotency_key": "k"},
    )


def test_live_poll_interval_is_read_from_configuration():
    from apps.core.models import Configuration
    from apps.orders import conf

    assert conf.live_poll_seconds() == 2
    Configuration.objects.update_or_create(
        config_set="orders", config_key="live_poll_seconds", defaults={"config_value": "5"}
    )
    assert conf.live_poll_seconds() == 5
