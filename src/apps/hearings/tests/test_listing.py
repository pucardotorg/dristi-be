"""The orders contract: hold, change, release, validate, confirm, cancel (spec 0023 #7)."""

import logging
import uuid

import pytest

from apps.api.errors import BusinessError
from apps.cases.models import CaseStatus
from apps.hearings import exceptions, signals
from apps.hearings.enums import (
    CalendarEntryType,
    CancellationReason,
    HearingStatus,
    ReleaseReason,
    RescheduleReason,
    Side,
)
from apps.hearings.models import CourtCalendarEntry, Hearing, HearingDateChange, HearingPurpose
from apps.hearings.services import calendar, courtroom, listing, reschedule
from apps.messaging.models import MessageLog

from .factories import (
    FRI,
    MON,
    SUN,
    TODAY,
    TUE,
    WED,
    code,
    hold,
    make_case,
    schedule,
    set_config,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def received():
    """Collect every hearings signal sent, by name."""
    seen = {}
    receivers = []
    for name in ("hearing_scheduled", "hearing_rescheduled", "hearing_ended", "hearing_cancelled"):

        def receiver(sender, _name=name, **kwargs):
            seen.setdefault(_name, []).append(kwargs)

        getattr(signals, name).connect(receiver, weak=False)
        receivers.append((name, receiver))
    yield seen
    for name, receiver in receivers:
        getattr(signals, name).disconnect(receiver)


def messages(case, key):
    return MessageLog.objects.filter(correlation_id=f"hearing:{case.pk}", message_key=key).count()


class TestHold:
    def test_hold_is_an_invisible_provisional_hearing(
        self, case, received, django_capture_on_commit_callbacks
    ):
        with django_capture_on_commit_callbacks(execute=True):
            result = hold(case, MON)
        hearing = result.hearing
        assert (hearing.status, hearing.sequence, hearing.original_date) == (
            HearingStatus.PROVISIONAL,
            None,
            MON,
        )
        assert result.load.provisional == 1
        assert received == {}
        assert messages(case, "HEARING_SCHEDULED") == 0

    def test_records_who_held_the_date(self, case, staff):
        hearing = hold(case, MON, actor=staff).hearing
        hearing.refresh_from_db()
        assert hearing.created_by == hearing.updated_by == staff
        assert hearing.history.get().history_user == staff

    def test_refusals(self, case, courtroom):
        unregistered = make_case(courtroom, status=CaseStatus.UNDER_SCRUTINY)
        with pytest.raises(exceptions.CaseNotListable) as excinfo:
            hold(unregistered, MON)
        assert excinfo.value.code == "E10003"
        assert "not registered in a court" in excinfo.value.message
        with pytest.raises(exceptions.InvalidHearingDate) as excinfo:
            hold(case, SUN)
        assert excinfo.value.code == "E10006"
        with pytest.raises(exceptions.InvalidPurpose):
            hold(case, MON, "NOPE")
        HearingPurpose.objects.filter(code="MEDIATION").update(is_active=False)
        with pytest.raises(exceptions.InvalidPurpose):
            hold(case, MON, "MEDIATION")
        assert not Hearing.objects.filter(case=case).exists()

    def test_not_after_previous(self, case):
        previous = schedule(case, WED)
        with pytest.raises(exceptions.InvalidHearingDate) as excinfo:
            hold(case, TUE, previous_hearing_id=previous.pk)
        assert excinfo.value.code == "E10008"

    def test_hold_again_for_the_same_order_is_a_change(self, case):
        order = uuid.uuid4()
        first = hold(case, MON, order_id=order).hearing
        second = hold(case, TUE, order_id=order).hearing
        assert second.pk == first.pk
        assert Hearing.objects.filter(source_order_id=order).count() == 1

    def test_hold_for_a_triggered_order_is_refused(self, case):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        listing.confirm(order_id=order)
        with pytest.raises(exceptions.HearingError) as excinfo:
            hold(case, TUE, order_id=order)
        assert excinfo.value.code == "E10001"

    def test_warnings(self, case, other_case):
        schedule(case, MON)
        result = hold(case, TUE)
        assert [w.code for w in result.warnings] == ["CASE_ALREADY_SCHEDULED"]
        result = hold(case, WED)
        assert "CASE_HELD_BY_ANOTHER_ORDER" in [w.code for w in result.warnings]

    def test_capacity_warn_and_block(self, case, other_case):
        set_config("max_hearings_per_day", "1")
        hold(case, MON)
        result = hold(other_case, MON)
        assert [w.code for w in result.warnings] == ["COURT_DAY_FULL"]
        set_config("capacity_mode", "block")
        with pytest.raises(exceptions.CourtDayFull):
            hold(make_case(case.court), MON)


class TestChange:
    def test_moves_the_hold_in_place_without_a_date_change(self, case):
        order = uuid.uuid4()
        held = hold(case, MON, order_id=order).hearing
        changed = listing.change(order_id=order, hearing_date=TUE, purpose_code="ARGUMENTS")
        assert changed.hearing.pk == held.pk
        held.refresh_from_db()
        assert (held.hearing_date, held.purpose.code, held.original_date) == (
            TUE,
            "ARGUMENTS",
            TUE,
        )
        assert not HearingDateChange.objects.exists()

    def test_unknown_order(self):
        with pytest.raises(exceptions.HoldNotFound):
            listing.change(order_id=uuid.uuid4(), hearing_date=TUE)

    def test_same_day_change_does_not_count_itself(self, case):
        set_config("max_hearings_per_day", "1")
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        assert listing.change(order_id=order, hearing_date=MON).warnings == []


class TestRelease:
    @pytest.mark.parametrize("reason", [ReleaseReason.DRAFT_DISCARDED, ReleaseReason.DATE_REMOVED])
    def test_release(self, case, reason):
        order = uuid.uuid4()
        held = hold(case, MON, order_id=order).hearing
        listing.release(order_id=order, reason=reason)
        held.refresh_from_db()
        assert (held.status, held.release_reason) == (HearingStatus.RELEASED, reason)

    def test_release_is_idempotent(self, case):
        order = uuid.uuid4()
        held = hold(case, MON, order_id=order).hearing
        listing.release(order_id=order, reason=ReleaseReason.DRAFT_DISCARDED)
        listing.release(order_id=order, reason=ReleaseReason.DATE_REMOVED)
        listing.release(order_id=uuid.uuid4(), reason=ReleaseReason.DATE_REMOVED)
        held.refresh_from_db()
        assert (held.status, held.release_reason) == (
            HearingStatus.RELEASED,
            ReleaseReason.DRAFT_DISCARDED,
        )

    def test_hearings_own_reasons_are_refused(self, case):
        with pytest.raises(ValueError):
            listing.release(order_id=uuid.uuid4(), reason=ReleaseReason.CONSUMED)


class TestConfirm:
    def test_confirm_schedules_and_announces(
        self, case, other_case, received, django_capture_on_commit_callbacks
    ):
        schedule(other_case, MON)
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        with django_capture_on_commit_callbacks(execute=True):
            hearing = listing.confirm(order_id=order)
        assert (hearing.status, hearing.sequence) == (HearingStatus.SCHEDULED, 2)
        assert hearing.confirmed_at is not None
        assert [s["hearing_id"] for s in received["hearing_scheduled"]] == [hearing.pk]
        assert messages(case, "HEARING_SCHEDULED") > 0

    def test_confirm_is_idempotent(self, case, received, django_capture_on_commit_callbacks):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        with django_capture_on_commit_callbacks(execute=True):
            first = listing.confirm(order_id=order)
        sent = messages(case, "HEARING_SCHEDULED")
        with django_capture_on_commit_callbacks(execute=True):
            again = listing.confirm(order_id=order)
        assert again.pk == first.pk
        assert len(received["hearing_scheduled"]) == 1
        assert messages(case, "HEARING_SCHEDULED") == sent
        assert listing.validate(order_id=order) == []

    def test_a_failing_signal_receiver_does_not_undo_the_hearing(
        self, case, received, caplog, django_capture_on_commit_callbacks
    ):
        def broken(sender, **kwargs):
            raise RuntimeError("listener down")

        signals.hearing_scheduled.connect(broken, weak=False)
        try:
            order = uuid.uuid4()
            hold(case, MON, order_id=order)
            with caplog.at_level(logging.ERROR, logger="apps.hearings.services.common"):
                with django_capture_on_commit_callbacks(execute=True):
                    hearing = listing.confirm(order_id=order)
        finally:
            signals.hearing_scheduled.disconnect(broken)
        hearing.refresh_from_db()
        assert hearing.status == HearingStatus.SCHEDULED
        assert [s["hearing_id"] for s in received["hearing_scheduled"]] == [hearing.pk]
        assert "HEARING_SIGNAL_RECEIVER_FAILED" in caplog.text

    def test_record_hearing_scheduled_is_called_once(
        self, case, monkeypatch, django_capture_on_commit_callbacks
    ):
        calls = []
        monkeypatch.setattr(
            "apps.hearings.services.common.record_hearing_scheduled",
            lambda **kwargs: calls.append(kwargs),
        )
        order = uuid.uuid4()
        hold(case, MON, "EVIDENCE_OF_COMPLAINANT", order_id=order)
        with django_capture_on_commit_callbacks(execute=True):
            listing.confirm(order_id=order)
        assert calls == [
            {"case_id": case.pk, "purpose_code": "EVIDENCE_OF_COMPLAINANT", "hearing_date": MON}
        ]

    def test_a_case_module_failure_does_not_undo_the_hearing(
        self, case, monkeypatch, django_capture_on_commit_callbacks
    ):
        def boom(**kwargs):
            raise RuntimeError("cases down")

        monkeypatch.setattr("apps.hearings.services.common.record_hearing_scheduled", boom)
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        with django_capture_on_commit_callbacks(execute=True):
            hearing = listing.confirm(order_id=order)
        hearing.refresh_from_db()
        assert hearing.status == HearingStatus.SCHEDULED

    def test_released_hold(self, case):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        listing.release(order_id=order, reason=ReleaseReason.DRAFT_DISCARDED)
        with pytest.raises(exceptions.HoldReleased) as excinfo:
            listing.confirm(order_id=order)
        assert "draft order discarded" in excinfo.value.message
        assert [p.error.code for p in listing.validate(order_id=order)] == ["E10021"]

    def test_unknown_order(self):
        with pytest.raises(exceptions.HoldNotFound):
            listing.confirm(order_id=uuid.uuid4())
        assert [p.error.code for p in listing.validate(order_id=uuid.uuid4())] == ["E10020"]

    def test_case_already_scheduled(self, case):
        scheduled = schedule(case, MON)
        order = uuid.uuid4()
        hold(case, TUE, order_id=order)
        assert [p.error.code for p in listing.validate(order_id=order)] == ["E10004"]
        with pytest.raises(exceptions.CaseAlreadyScheduled) as excinfo:
            listing.confirm(order_id=order)
        assert excinfo.value.hearing_id == scheduled.pk

    def test_date_passed(self, case):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        set_config("business_date_override", TUE.isoformat())
        assert [p.error.code for p in listing.validate(order_id=order)] == ["E10005"]
        with pytest.raises(exceptions.HoldInvalid):
            listing.confirm(order_id=order)

    def test_date_became_a_holiday(self, case):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        CourtCalendarEntry.objects.create(
            court=case.court, date=MON, entry_type=CalendarEntryType.HOLIDAY, reason="Declared"
        )
        with pytest.raises(exceptions.HoldInvalid) as excinfo:
            listing.confirm(order_id=order)
        assert [p.error.code for p in excinfo.value.problems] == ["E10006"]

    def test_case_no_longer_listable(self, case):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        type(case).objects.filter(pk=case.pk).update(status=CaseStatus.PENDING_REGISTRATION)
        with pytest.raises(exceptions.HoldInvalid) as excinfo:
            listing.confirm(order_id=order)
        assert [p.error.code for p in excinfo.value.problems] == ["E10003"]

    def test_a_date_problem_wins_over_already_scheduled(self, case):
        schedule(case, MON)
        order = uuid.uuid4()
        hold(case, TUE, order_id=order)
        type(case).objects.filter(pk=case.pk).update(status=CaseStatus.PENDING_REGISTRATION)
        with pytest.raises(exceptions.HoldInvalid) as excinfo:
            listing.confirm(order_id=order)
        assert [p.error.code for p in excinfo.value.problems] == ["E10003", "E10004"]

    def test_nothing_is_sent_on_rollback(self, case, received, django_capture_on_commit_callbacks):
        from django.db import transaction

        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        with django_capture_on_commit_callbacks(execute=True):
            with pytest.raises(RuntimeError):
                with transaction.atomic():
                    listing.confirm(order_id=order)
                    raise RuntimeError("a later workflow of the order failed")
        assert received == {}
        assert Hearing.objects.get(source_order_id=order).status == HearingStatus.PROVISIONAL


class TestHeldMove:
    def test_original_stays_until_triggered_then_moves_in_place(
        self, case, received, django_capture_on_commit_callbacks
    ):
        original = schedule(case, MON)
        order = uuid.uuid4()
        held = hold(case, WED, "ARGUMENTS", order_id=order, moves_hearing_id=original.pk)
        assert "CASE_ALREADY_SCHEDULED" not in [w.code for w in held.warnings]
        original.refresh_from_db()
        assert original.hearing_date == MON
        with django_capture_on_commit_callbacks(execute=True):
            moved = listing.confirm(
                order_id=order,
                reason_code=RescheduleReason.PARTY_APPLICATION,
                sought_by=Side.ACCUSED,
            )
        original.refresh_from_db()
        assert moved.pk == original.pk
        assert (original.hearing_date, original.purpose.code, original.reschedule_count) == (
            WED,
            "ARGUMENTS",
            1,
        )
        assert original.original_date == MON
        change = HearingDateChange.objects.get(hearing=original)
        assert (change.source, change.source_ref, change.sought_by) == ("ORDER", order, "ACCUSED")
        held.hearing.refresh_from_db()
        assert held.hearing.release_reason == ReleaseReason.CONSUMED
        assert [(s["from_date"], s["to_date"]) for s in received["hearing_rescheduled"]] == [
            (MON, WED)
        ]
        assert listing.confirm(order_id=order).pk == original.pk

    def test_a_move_must_change_something(self, case):
        original = schedule(case, MON)
        with pytest.raises(exceptions.HearingError) as excinfo:
            hold(case, MON, moves_hearing_id=original.pk)
        assert excinfo.value.code == "E10012"
        order = uuid.uuid4()
        hold(case, WED, order_id=order, moves_hearing_id=original.pk)
        with pytest.raises(exceptions.HearingError):
            listing.change(order_id=order, hearing_date=MON)

    def test_original_cancelled_after_the_hold(self, case):
        original = schedule(case, MON)
        order = uuid.uuid4()
        hold(case, WED, order_id=order, moves_hearing_id=original.pk)
        listing.cancel_listed_in_error(hearing_id=original.pk)
        assert [p.error.code for p in listing.validate(order_id=order)] == ["E10001"]
        with pytest.raises(exceptions.HoldInvalid):
            listing.confirm(order_id=order)

    def test_original_already_moved_to_the_held_date(self, case):
        original = schedule(case, MON)
        order = uuid.uuid4()
        hold(case, WED, order_id=order, moves_hearing_id=original.pk)
        reschedule.reschedule(
            hearing_id=original.pk, hearing_date=WED, reason_code=RescheduleReason.NOT_REACHED
        )
        assert [p.error.code for p in listing.validate(order_id=order)] == ["E10012"]
        with pytest.raises(exceptions.HoldInvalid):
            listing.confirm(order_id=order)

    def test_case_scheduled_again_while_the_move_was_held(self, case):
        abandoned = schedule(case, TODAY)
        courtroom.end_day(case.court_id, TODAY)
        set_config("business_date_override", MON.isoformat())
        order = uuid.uuid4()
        hold(case, WED, order_id=order, moves_hearing_id=abandoned.pk)
        fresh = schedule(case, TUE)
        assert [p.error.code for p in listing.validate(order_id=order)] == ["E10004"]
        with pytest.raises(exceptions.CaseAlreadyScheduled) as excinfo:
            listing.confirm(order_id=order)
        assert excinfo.value.hearing_id == fresh.pk

    def test_cannot_hold_a_move_of_a_heard_hearing(self, case):
        original = schedule(case, TODAY)
        courtroom.start(hearing_id=original.pk)
        courtroom.end(hearing_id=original.pk)
        with pytest.raises(exceptions.HearingError) as excinfo:
            hold(case, WED, moves_hearing_id=original.pk)
        assert excinfo.value.code == "E10001"


class TestConcurrentOrderCalls:
    """Another worker finishes a call on the same order while this one waits for the court lock.

    The orders module retries a trigger, and a draft can be edited or discarded
    while it is being triggered; each call re-reads the hold under the lock (#11.5).
    """

    @pytest.fixture
    def meanwhile(self, monkeypatch):
        """Let ``other`` commit between this call's first read of the hold and its lock.

        That is the window a worker holding the court lock leaves open. ``other``
        runs outside this call's transaction, so its writes stand on their own.
        """

        def install(other):
            real_read = listing._current_hold
            pending = [other]

            def current_hold(order_id, *, lock=False):
                found = real_read(order_id, lock=lock)
                if pending and not lock:
                    pending.pop()()
                return found

            monkeypatch.setattr(listing, "_current_hold", current_hold)

        return install

    def test_retried_trigger_returns_the_hearing_already_scheduled(
        self, case, meanwhile, received, django_capture_on_commit_callbacks
    ):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        first = []
        meanwhile(lambda: first.append(listing.confirm(order_id=order)))
        with django_capture_on_commit_callbacks(execute=True):
            retried = listing.confirm(order_id=order)
        assert retried.pk == first[0].pk
        assert retried.status == HearingStatus.SCHEDULED
        assert Hearing.objects.filter(source_order_id=order).count() == 1
        assert len(received["hearing_scheduled"]) == 1

    def test_trigger_after_the_draft_was_discarded(self, case, meanwhile):
        order = uuid.uuid4()
        held = hold(case, MON, order_id=order).hearing
        meanwhile(lambda: listing.release(order_id=order, reason=ReleaseReason.DRAFT_DISCARDED))
        with pytest.raises(exceptions.HoldReleased):
            listing.confirm(order_id=order)
        held.refresh_from_db()
        assert held.status == HearingStatus.RELEASED

    def test_draft_edit_after_the_trigger_changes_nothing(self, case, meanwhile):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        meanwhile(lambda: listing.confirm(order_id=order))
        with pytest.raises(exceptions.HoldNotFound):
            listing.change(order_id=order, hearing_date=TUE)
        hearing = Hearing.objects.get(source_order_id=order)
        assert (hearing.status, hearing.hearing_date) == (HearingStatus.SCHEDULED, MON)

    def test_discard_after_the_trigger_leaves_the_hearing_scheduled(self, case, meanwhile):
        order = uuid.uuid4()
        hold(case, MON, order_id=order)
        meanwhile(lambda: listing.confirm(order_id=order))
        listing.release(order_id=order, reason=ReleaseReason.DRAFT_DISCARDED)
        hearing = Hearing.objects.get(source_order_id=order)
        assert (hearing.status, hearing.release_reason) == (HearingStatus.SCHEDULED, "")


class TestAttachOrder:
    def test_attach(self, case):
        hearing = schedule(case, MON)
        order = uuid.uuid4()
        listing.attach_order(hearing_id=hearing.pk, order_id=order)
        listing.attach_order(hearing_id=hearing.pk, order_id=str(order))
        hearing.refresh_from_db()
        assert hearing.order_id == order
        with pytest.raises(exceptions.HearingError):
            listing.attach_order(hearing_id=hearing.pk, order_id=uuid.uuid4())

    def test_not_on_a_hold(self, case):
        held = hold(case, MON).hearing
        with pytest.raises(exceptions.HearingError):
            listing.attach_order(hearing_id=held.pk, order_id=uuid.uuid4())


class TestCancel:
    def test_case_closure(self, case, received, django_capture_on_commit_callbacks):
        listed = schedule(case, MON)
        other_draft = hold(case, TUE).hearing
        closing_order = uuid.uuid4()
        own = hold(case, WED, order_id=closing_order).hearing
        with django_capture_on_commit_callbacks(execute=True):
            changed = listing.cancel_open_hearings(
                case_id=case.pk, reason=CancellationReason.CASE_DISPOSED, order_id=closing_order
            )
        assert {h.pk for h in changed} == {listed.pk, other_draft.pk}
        listed.refresh_from_db()
        other_draft.refresh_from_db()
        own.refresh_from_db()
        assert (listed.status, listed.cancellation_reason) == ("CANCELLED", "CASE_DISPOSED")
        assert listed.sequence is not None
        assert other_draft.release_reason == ReleaseReason.CASE_CLOSED
        assert own.status == HearingStatus.PROVISIONAL
        assert [s["hearing_id"] for s in received["hearing_cancelled"]] == [listed.pk]
        assert messages(case, "HEARING_CANCELLED") > 0

    def test_hearing_in_progress_is_left_alone(self, case):
        today = schedule(case, TODAY)
        courtroom.start(hearing_id=today.pk)
        listing.cancel_open_hearings(case_id=case.pk, reason=CancellationReason.CASE_TRANSFERRED)
        today.refresh_from_db()
        assert today.status == HearingStatus.IN_PROGRESS

    def test_listed_in_error(self, case, staff):
        hearing = schedule(case, MON)
        stamp = hearing.updated_at
        with pytest.raises(BusinessError) as excinfo:
            listing.cancel_listed_in_error(
                hearing_id=hearing.pk,
                if_unmodified_since=stamp.replace(year=stamp.year - 1),
            )
        assert code(excinfo) == "E10002"
        cancelled = listing.cancel_listed_in_error(hearing_id=hearing.pk, actor=staff)
        assert cancelled.cancellation_reason == CancellationReason.LISTED_IN_ERROR
        with pytest.raises(BusinessError) as excinfo:
            listing.cancel_listed_in_error(hearing_id=hearing.pk)
        assert code(excinfo) == "E10001"
        assert excinfo.value.allowed_actions == []

    def test_unknown_reason(self, case):
        with pytest.raises(ValueError):
            listing.cancel_open_hearings(case_id=case.pk, reason="NOPE")


def test_hold_counts_in_the_load_until_confirmed(case, courtroom):
    order = uuid.uuid4()
    hold(case, FRI, order_id=order)
    assert calendar.day_load(courtroom.pk, FRI).provisional == 1
    listing.confirm(order_id=order)
    load = calendar.day_load(courtroom.pk, FRI)
    assert (load.listed, load.provisional) == (1, 0)
