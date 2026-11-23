"""The next hearing (spec 0039 #6.4): one value per order, from the order or the cause list."""

import datetime

import pytest
from rest_framework.exceptions import ValidationError

from apps.api.errors import BusinessError
from apps.hearings.enums import HearingStatus, ReleaseReason
from apps.hearings.exceptions import HearingError
from apps.hearings.models import Hearing
from apps.orders.enums import EnteredFrom, ItemSource, NextHearingState
from apps.orders.models import Order
from apps.orders.services import bulk, drafting, next_hearing

from .factories import TODAY, code, schedule, started_hearing

pytestmark = pytest.mark.django_db

NEXT = TODAY.replace(day=19)  # a Thursday after TODAY
LATER = TODAY.replace(day=26)


def hold_of(order):
    return Hearing.objects.filter(source_order_id=order.pk).first()


def set_(order, setter, **kwargs):
    kwargs.setdefault("state", "LISTED")
    return next_hearing.set_next_hearing(order.pk, actor=setter, **kwargs)


# -- in a hearing ----------------------------------------------------------------------


def test_a_date_is_held_provisionally_from_the_moment_it_is_set(order, setter):
    updated, _ = set_(order, setter, date=NEXT, purpose="EVIDENCE_OF_COMPLAINANT")
    held = hold_of(order)
    assert held.status == HearingStatus.PROVISIONAL
    assert held.hearing_date == NEXT
    assert held.previous_hearing_id == order.hearing_id
    assert updated.next_hearing_state == NextHearingState.LISTED
    assert updated.next_hearing_held is True
    assert updated.next_hearing_entered_from == EnteredFrom.ORDER


def test_changing_the_date_changes_the_hold_in_place(order, setter):
    set_(order, setter, date=NEXT, purpose="APPEARANCE")
    first = hold_of(order)
    set_(order, setter, date=LATER, purpose="ARGUMENTS")
    assert Hearing.objects.filter(source_order_id=order.pk).count() == 1
    first.refresh_from_db()
    assert (first.hearing_date, first.purpose.code) == (LATER, "ARGUMENTS")


def test_not_listed_again_releases_the_hold(order, setter):
    set_(order, setter, date=NEXT, purpose="APPEARANCE")
    updated, _ = set_(order, setter, state="NOT_LISTED_AGAIN")
    held = Hearing.objects.get(source_order_id=order.pk)
    assert held.status == HearingStatus.RELEASED
    assert held.release_reason == ReleaseReason.DATE_REMOVED
    assert updated.next_hearing_state == NextHearingState.NOT_LISTED_AGAIN
    assert updated.next_hearing_date is None
    assert updated.next_hearing_held is False


@pytest.mark.parametrize("kwargs", [{"date": NEXT}, {"purpose": "APPEARANCE"}])
def test_half_a_next_hearing_is_refused(order, setter, kwargs):
    with pytest.raises(Exception) as excinfo:
        set_(order, setter, **kwargs)
    assert excinfo.value.detail.keys() & {"date", "purpose"}
    assert hold_of(order) is None


def test_not_listed_again_takes_no_date(order, setter):
    with pytest.raises(ValidationError):
        set_(order, setter, state="NOT_LISTED_AGAIN", date=NEXT)


def test_hearings_errors_pass_through_unchanged(order, setter):
    with pytest.raises(BusinessError) as excinfo:
        set_(order, setter, date=TODAY - datetime.timedelta(days=1), purpose="APPEARANCE")
    assert code(excinfo) == "E10005"
    with pytest.raises(BusinessError) as excinfo:
        set_(order, setter, date=NEXT, purpose="NOT_A_PURPOSE")
    assert code(excinfo) == "E10014"
    sunday = TODAY + datetime.timedelta(days=3)
    with pytest.raises(BusinessError) as excinfo:
        set_(order, setter, date=sunday, purpose="APPEARANCE")
    assert code(excinfo) == "E10006"


def test_a_hearings_soft_warnings_come_back(order, setter, other_case, third_case):
    from apps.hearings.tests.factories import hold, set_config

    set_config("max_hearings_per_day", "1")
    hold(other_case, NEXT)
    _, warnings = set_(order, setter, date=NEXT, purpose="APPEARANCE")
    assert any("full" in w.message.lower() or "capacity" in w.message.lower() for w in warnings)


def test_the_next_hearing_is_frozen_once_sent_for_signing(ready, setter, staff):
    from apps.orders.services import lifecycle

    lifecycle.send_for_signing(ready.pk, actor=staff)
    with pytest.raises(BusinessError) as excinfo:
        set_(ready, setter, date=LATER, purpose="APPEARANCE")
    assert code(excinfo) == "E14001"


def test_the_next_hearing_checks_the_data_version(order, setter):
    with pytest.raises(BusinessError) as excinfo:
        set_(order, setter, date=NEXT, purpose="APPEARANCE", data_version=99)
    assert code(excinfo) == "E14002"


# -- outside a hearing -------------------------------------------------------------------


def system_items(order):
    return list(order.items.filter(added_by_source=ItemSource.SYSTEM).select_related("item_type"))


def test_a_different_date_outside_a_hearing_holds_a_move_and_adds_rescheduling(
    case, drafter, setter
):
    listed = schedule(case, NEXT, "EVIDENCE_OF_COMPLAINANT")
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    assert order.next_hearing_date == NEXT
    updated, _ = set_(order, setter, date=LATER, purpose="EVIDENCE_OF_COMPLAINANT")
    held = hold_of(order)
    assert held.moves_hearing_id == listed.pk
    assert held.hearing_date == LATER
    (item,) = system_items(order)
    assert item.item_type.code == "RESCHEDULING_OF_HEARING_DATE"
    assert item.values == {
        "new_hearing_date": LATER.isoformat(),
        "hearing_purpose": "EVIDENCE_OF_COMPLAINANT",
        "original_hearing_date": NEXT.isoformat(),
    }
    assert updated.moves_hearing_id == listed.pk
    # The original stays where it is until the order is triggered.
    listed.refresh_from_db()
    assert listed.hearing_date == NEXT


def test_returning_to_the_listed_hearing_releases_the_hold_and_removes_the_item(
    case, drafter, setter
):
    schedule(case, NEXT, "EVIDENCE_OF_COMPLAINANT")
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    set_(order, setter, date=LATER, purpose="ARGUMENTS")
    updated, _ = set_(order, setter, date=NEXT, purpose="EVIDENCE_OF_COMPLAINANT")
    assert hold_of(order).status == HearingStatus.RELEASED
    assert system_items(order) == []
    assert updated.next_hearing_held is False
    assert updated.moves_hearing_id is None
    assert updated.next_hearing_state == NextHearingState.LISTED


def test_a_case_with_no_listed_hearing_gets_a_scheduling_item(case, drafter, setter):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    assert order.next_hearing_state == NextHearingState.UNSET
    set_(order, setter, date=NEXT, purpose="ADMISSION")
    (item,) = system_items(order)
    assert item.item_type.code == "SCHEDULING_OF_HEARING_DATE"
    assert item.values["hearing_date"] == NEXT.isoformat()
    # Changing the date updates the one item rather than adding another.
    set_(order, setter, date=LATER, purpose="ADMISSION")
    (item,) = system_items(order)
    assert item.values["hearing_date"] == LATER.isoformat()


def test_not_listed_again_outside_a_hearing_drops_the_system_item(case, drafter, setter):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    set_(order, setter, date=NEXT, purpose="ADMISSION")
    set_(order, setter, state="NOT_LISTED_AGAIN")
    assert system_items(order) == []
    assert hold_of(order).status == HearingStatus.RELEASED


def test_a_date_change_reopens_complete_order_data(case, drafter, setter, filler):
    from apps.orders.services import lifecycle

    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    set_(order, setter, date=NEXT, purpose="ADMISSION")
    lifecycle.mark_complete(order.pk, actor=filler)
    assert Order.objects.get(pk=order.pk).data_complete is True
    set_(order, setter, date=LATER, purpose="ADMISSION")
    assert Order.objects.get(pk=order.pk).data_complete is False


# -- the cause list ------------------------------------------------------------------------


def test_a_value_set_on_the_cause_list_shows_on_the_order_and_the_other_way_round(
    hearing, order, setter
):
    bulk.set_for_hearing(
        actor=setter, hearing_id=hearing.pk, state="LISTED", date=NEXT, purpose="APPEARANCE"
    )
    order.refresh_from_db()
    assert order.next_hearing_date == NEXT
    assert order.next_hearing_entered_from == EnteredFrom.CAUSE_LIST
    set_(order, setter, date=LATER, purpose="APPEARANCE")
    order.refresh_from_db()
    assert order.next_hearing_entered_from == EnteredFrom.ORDER
    assert hold_of(order).hearing_date == LATER


def test_the_cause_list_column_is_refused_before_the_hearing_starts(case, setter):
    scheduled = schedule(case, TODAY)
    with pytest.raises(BusinessError) as excinfo:
        bulk.set_for_hearing(
            actor=setter, hearing_id=scheduled.pk, state="LISTED", date=NEXT, purpose="APPEARANCE"
        )
    assert code(excinfo) == "E14004"


def test_the_bulk_action_reaches_a_listing_not_yet_started_by_creating_its_draft(
    case, courtroom, setter
):
    scheduled = schedule(case, TODAY)
    result = bulk.bulk_next_hearing(
        actor=setter,
        court_id=courtroom.pk,
        hearing_ids=[scheduled.pk],
        state="LISTED",
        date=NEXT,
        purpose=None,
    )
    assert result["done"] == [scheduled.pk]
    order = Order.objects.get(hearing_id=scheduled.pk)
    # No purpose given: the hearing's own is kept.
    assert order.next_hearing_purpose == "APPEARANCE"
    assert order.status == "DRAFT"


def test_started_hearings_keep_a_purpose_the_order_already_has(hearing, order, setter, courtroom):
    set_(order, setter, date=NEXT, purpose="ARGUMENTS")
    bulk.bulk_next_hearing(
        actor=setter, court_id=courtroom.pk, hearing_ids=[hearing.pk], state="LISTED", date=LATER
    )
    order.refresh_from_db()
    assert (order.next_hearing_date, order.next_hearing_purpose) == (LATER, "ARGUMENTS")
    assert HearingError and started_hearing
