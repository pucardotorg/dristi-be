"""Bulk actions (spec 0039 #10.3-#10.5): what each one skips and names, and why."""

import uuid

import pytest
from rest_framework.exceptions import ValidationError

from apps.orders.enums import OrderStatus
from apps.orders.models import Order
from apps.orders.services import bulk, drafting, lifecycle

from .factories import TODAY, make_case, started_hearing

pytestmark = pytest.mark.django_db

NEXT = TODAY.replace(day=19)


def codes(result, key):
    return [(skipped[key], skipped["code"]) for skipped in result["skipped"]]


def test_bulk_items_refuse_orders_of_more_than_one_courtroom(
    order, sibling_courtroom, drafter, staff
):
    other_hearing = started_hearing(make_case(sibling_courtroom), staff)
    other = drafting.create_in_hearing(hearing_id=other_hearing.pk, actor=drafter)[0]
    with pytest.raises(ValidationError) as excinfo:
        bulk.bulk_items(
            actor=staff, order_ids=[order.pk, other.pk], item_specs=[{"item_type": "COST"}]
        )
    assert excinfo.value.detail["order_ids"][0].code == "E14011"
    assert not order.items.exists() and not other.items.exists()


def test_bulk_items_name_an_order_not_found_and_carry_on(order, staff):
    missing = uuid.uuid4()
    result = bulk.bulk_items(
        actor=staff, order_ids=[missing, order.pk], item_specs=[{"item_type": "COST"}]
    )
    assert result["done"] == [order.pk]
    assert codes(result, "order_id") == [(missing, "E00105")]
    assert order.items.count() == 1


def test_bulk_text_names_a_hearing_not_found_or_of_another_courtroom(
    hearing, case, sibling_courtroom, staff
):
    elsewhere = started_hearing(make_case(sibling_courtroom), staff)
    missing = uuid.uuid4()
    result = bulk.bulk_text(
        actor=staff,
        court_id=case.court_id,
        hearing_ids=[missing, elsewhere.pk, hearing.pk],
        text="<p>Adjourned.</p>",
    )
    assert result["done"] == [hearing.pk]
    assert codes(result, "hearing_id") == [(missing, "E00105"), (elsewhere.pk, "E00105")]
    assert not Order.objects.filter(hearing_id=elsewhere.pk).exists()


def test_bulk_text_skips_an_order_already_sent_for_signing(ready, hearing, case, staff):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    text = Order.objects.get(pk=ready.pk).text
    result = bulk.bulk_text(
        actor=staff, court_id=case.court_id, hearing_ids=[hearing.pk], text="<p>More.</p>"
    )
    assert result["done"] == []
    assert codes(result, "hearing_id") == [(hearing.pk, "E14001")]
    assert Order.objects.get(pk=ready.pk).text == text


def test_bulk_next_hearing_names_a_hearing_not_found(hearing, case, staff):
    missing = uuid.uuid4()
    result = bulk.bulk_next_hearing(
        actor=staff,
        court_id=case.court_id,
        hearing_ids=[missing, hearing.pk],
        state="NOT_LISTED_AGAIN",
    )
    assert result["done"] == [hearing.pk]
    assert codes(result, "hearing_id") == [(missing, "E00105")]


def test_bulk_next_hearing_skips_an_order_already_sent_for_signing(ready, hearing, case, staff):
    lifecycle.send_for_signing(ready.pk, actor=staff)
    before = Order.objects.get(pk=ready.pk)
    result = bulk.bulk_next_hearing(
        actor=staff,
        court_id=case.court_id,
        hearing_ids=[hearing.pk],
        state="NOT_LISTED_AGAIN",
    )
    assert result["done"] == []
    assert codes(result, "hearing_id") == [(hearing.pk, "E14001")]
    after = Order.objects.get(pk=ready.pk)
    assert after.status == OrderStatus.SENT_FOR_SIGNING
    assert (after.next_hearing_state, after.next_hearing_date) == (
        before.next_hearing_state,
        before.next_hearing_date,
    )
