"""The next hearing (spec 0039 #6.4): one value per order, from the order or the cause list."""

import datetime

import pytest
from rest_framework.exceptions import ValidationError

from apps.api.errors import BusinessError
from apps.hearings.enums import HearingStatus, ReleaseReason
from apps.hearings.exceptions import HearingError
from apps.hearings.models import Hearing
from apps.orders import conf, errors
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


def test_bulk_items_roll_back_an_orders_earlier_items_when_a_later_one_fails(
    order,
    courtroom,
    filler,
    staff,
):
    result = bulk.bulk_items(
        actor=staff,
        order_ids=[order.pk],
        item_specs=[{"item_type": "COST"}, {"item_type": "COST", "values": {"nope": 1}}],
    )
    assert result["done"] == []
    assert [s["order_id"] for s in result["skipped"]] == [order.pk]
    assert order.items.count() == 0


def test_bulk_items_commit_each_order_that_succeeds(order, staff):
    result = bulk.bulk_items(actor=staff, order_ids=[order.pk], item_specs=[{"item_type": "COST"}])
    assert result["done"] == [order.pk] and order.items.count() == 1


def test_bulk_text_skips_an_unstarted_hearing_even_with_a_draft(case, staff):
    hearing = schedule(case, TODAY)  # scheduled, not started
    bulk.bulk_next_hearing(
        actor=staff,
        court_id=case.court_id,
        hearing_ids=[hearing.pk],
        state="NOT_LISTED_AGAIN",
    )
    draft = Order.objects.get(hearing_id=hearing.pk)
    assert draft.text == ""
    result = bulk.bulk_text(
        actor=staff, court_id=case.court_id, hearing_ids=[hearing.pk], text="<p>Hi.</p>"
    )
    assert result["done"] == []
    assert [(s["hearing_id"], s["code"]) for s in result["skipped"]] == [(hearing.pk, "E14004")]
    assert Order.objects.get(pk=draft.pk).text == ""


def test_bulk_text_still_appends_for_a_started_hearing_with_a_draft(order, hearing, case, staff):
    result = bulk.bulk_text(
        actor=staff, court_id=case.court_id, hearing_ids=[hearing.pk], text="<p>Hi.</p>"
    )
    assert result["done"] == [hearing.pk]


def test_bulk_next_hearing_with_the_current_purpose_refuses_a_stale_snapshot(
    order, hearing, case, staff, monkeypatch
):
    real = next_hearing.set_next_hearing
    seen = {}

    def spy(order_id, **kwargs):
        seen.update(kwargs)
        # A concurrent edit lands between the snapshot and the locked write.
        Order.objects.filter(pk=order_id).update(data_version=kwargs["data_version"] + 1)
        return real(order_id, **kwargs)

    monkeypatch.setattr(next_hearing, "set_next_hearing", spy)
    result = bulk.bulk_next_hearing(
        actor=staff,
        court_id=case.court_id,
        hearing_ids=[hearing.pk],
        state="LISTED",
        date=TODAY.replace(day=19),
    )
    assert seen["data_version"] is not None
    assert result["done"] == []
    assert [s["code"] for s in result["skipped"]] == ["E14002"]


def test_bulk_next_hearing_with_an_explicit_purpose_keeps_last_write_wins(
    order, hearing, case, staff, monkeypatch
):
    seen = {}
    real = next_hearing.set_next_hearing

    def spy(order_id, **kwargs):
        seen.update(kwargs)
        return real(order_id, **kwargs)

    monkeypatch.setattr(next_hearing, "set_next_hearing", spy)
    result = bulk.bulk_next_hearing(
        actor=staff,
        court_id=case.court_id,
        hearing_ids=[hearing.pk],
        state="LISTED",
        date=TODAY.replace(day=19),
        purpose="EVIDENCE_OF_COMPLAINANT",
    )
    assert seen["data_version"] is None and result["done"] == [hearing.pk]
    assert started_hearing and drafting


def test_a_hold_is_replaced_when_the_hearing_it_moves_changes(case, drafter, setter):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    next_hearing.set_next_hearing(
        order.pk, state="LISTED", date=TODAY.replace(day=26), purpose="ARGUMENTS", actor=setter
    )
    other = schedule(case, TODAY.replace(day=19), "EVIDENCE_OF_COMPLAINANT")  # another order's
    next_hearing.set_next_hearing(
        order.pk,
        state="LISTED",
        date=TODAY.replace(day=26),
        purpose="EVIDENCE_OF_COMPLAINANT",
        actor=setter,
    )
    order.refresh_from_db()
    assert order.moves_hearing_id == other.pk
    held = Hearing.objects.get(source_order_id=order.pk, status="PROVISIONAL")
    assert held.moves_hearing_id == other.pk
    assert order.items.get().item_type.code == "RESCHEDULING_OF_HEARING_DATE"


def test_the_first_date_item_reopens_completed_order_data(case, drafter, setter):
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    Order.objects.filter(pk=order.pk).update(data_complete=True)
    next_hearing.set_next_hearing(
        order.pk, state="LISTED", date=TODAY.replace(day=26), purpose="ARGUMENTS", actor=setter
    )
    order.refresh_from_db()
    assert order.data_complete is False
    assert order.items.get().item_type.code == "SCHEDULING_OF_HEARING_DATE"


def test_the_listed_hearing_is_read_after_the_court_lock(case, drafter, setter, monkeypatch):
    from apps.hearings import selectors as hearing_selectors
    from apps.hearings.services import calendar

    calls = []
    real_lock, real_read = calendar.lock_court, hearing_selectors.scheduled_hearing
    monkeypatch.setattr(calendar, "lock_court", lambda c: (calls.append("lock"), real_lock(c))[1])
    monkeypatch.setattr(
        hearing_selectors, "scheduled_hearing", lambda c: (calls.append("read"), real_read(c))[1]
    )
    order = drafting.create_outside_hearing(case_id=case.pk, actor=drafter)
    calls.clear()
    next_hearing.set_next_hearing(
        order.pk, state="LISTED", date=TODAY.replace(day=26), purpose="ARGUMENTS", actor=setter
    )
    assert calls.index("lock") < calls.index("read")


# -- one transaction per listing in the bulk actions and the cause-list column ---------------


def test_bulk_text_leaves_no_draft_when_the_append_fails(started, case, staff):
    too_long = f"<p>{'x' * (conf.text_max_bytes() + 1)}</p>"
    result = bulk.bulk_text(
        actor=staff, court_id=case.court_id, hearing_ids=[started.pk], text=too_long
    )
    assert result["done"] == []
    assert [s["hearing_id"] for s in result["skipped"]] == [started.pk]
    assert not Order.objects.filter(hearing_id=started.pk).exists()


def test_bulk_text_keeps_the_drafts_of_the_listings_that_succeed(started, case, staff):
    result = bulk.bulk_text(
        actor=staff, court_id=case.court_id, hearing_ids=[started.pk], text="<p>Hi.</p>"
    )
    assert result["done"] == [started.pk]
    assert Order.objects.get(hearing_id=started.pk).text == "<p>Hi.</p>"


def test_bulk_next_hearing_leaves_no_draft_when_the_date_is_rejected(
    case, courtroom, staff, monkeypatch
):
    scheduled = schedule(case, TODAY)

    def reject(order_id, **kwargs):
        raise BusinessError(errors.INVALID_ORDER_ACTION, "The date is refused.")

    monkeypatch.setattr(next_hearing, "set_next_hearing", reject)
    result = bulk.bulk_next_hearing(
        actor=staff,
        court_id=courtroom.pk,
        hearing_ids=[scheduled.pk],
        state="LISTED",
        date=NEXT,
    )
    assert result["done"] == []
    assert [s["hearing_id"] for s in result["skipped"]] == [scheduled.pk]
    assert not Order.objects.filter(hearing_id=scheduled.pk).exists()


def test_set_for_hearing_leaves_no_draft_on_a_stale_version(started, staff):
    with pytest.raises(BusinessError) as excinfo:
        bulk.set_for_hearing(
            actor=staff,
            hearing_id=started.pk,
            state="LISTED",
            date=NEXT,
            purpose="APPEARANCE",
            data_version=1,
        )
    assert code(excinfo) == "E14002"
    assert not Order.objects.filter(hearing_id=started.pk).exists()


def test_set_for_hearing_creates_the_draft_on_a_valid_first_edit(started, staff):
    order, _ = bulk.set_for_hearing(
        actor=staff,
        hearing_id=started.pk,
        state="LISTED",
        date=NEXT,
        purpose="APPEARANCE",
        data_version=0,
    )
    assert Order.objects.get(hearing_id=started.pk).pk == order.pk


@pytest.mark.parametrize("empty", [None, ""])
def test_bulk_next_hearing_checks_the_version_for_an_omitted_purpose(
    order, hearing, case, staff, monkeypatch, empty
):
    seen = {}
    real = next_hearing.set_next_hearing

    def spy(order_id, **kwargs):
        seen.update(kwargs)
        return real(order_id, **kwargs)

    monkeypatch.setattr(next_hearing, "set_next_hearing", spy)
    bulk.bulk_next_hearing(
        actor=staff,
        court_id=case.court_id,
        hearing_ids=[hearing.pk],
        state="LISTED",
        date=NEXT,
        purpose=empty,
    )
    assert seen["data_version"] is not None


@pytest.fixture
def started(case, staff):
    """A started hearing with no order yet."""
    return started_hearing(case, staff)
