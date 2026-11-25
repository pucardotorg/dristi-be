"""Reads (spec 0039 #4, #6.6): whose move it is and the diary entries by date."""

import datetime

import pytest

from apps.orders import selectors
from apps.orders.enums import OrderStatus, RoznamaStatus
from apps.orders.models import Order, OrderRoznama

from .test_triggering import trigger

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("status", "data_complete", "line"),
    [
        (OrderStatus.DRAFT, False, "Being drafted by an order drafter"),
        (OrderStatus.SENT_FOR_SIGNING, True, "Awaiting signature by an order signer"),
        (
            OrderStatus.SENT_FOR_SIGNING,
            False,
            "Awaiting signature by an order signer, and order data by an order data filler",
        ),
        (OrderStatus.SIGNED, False, "Order data to be completed by an order data filler"),
        (OrderStatus.TRIGGERED, True, ""),
    ],
)
def test_whose_move_follows_the_orders_status_and_data(status, data_complete, line):
    assert selectors.whose_move(Order(status=status, data_complete=data_complete)) == line


def test_a_triggered_order_waits_on_its_roznamas_signature_until_signed():
    order = Order(status=OrderStatus.TRIGGERED, data_complete=True)
    awaiting = OrderRoznama(status=RoznamaStatus.AWAITING_SIGNATURE)
    assert selectors.whose_move(order, awaiting) == "Roznama awaiting signature by an order signer"
    assert selectors.whose_move(order, OrderRoznama(status=RoznamaStatus.SIGNED)) == ""


def test_diary_entries_filter_by_the_hearing_or_order_date(ready, staff, signer, courtroom):
    order = trigger(ready, staff, signer)
    on_the_day = selectors.diary_entries(courtroom.pk, date=order.hearing.hearing_date)
    assert [row["order_id"] for row in on_the_day] == [order.pk]
    another_day = order.hearing.hearing_date - datetime.timedelta(days=30)
    assert selectors.diary_entries(courtroom.pk, date=another_day) == []
