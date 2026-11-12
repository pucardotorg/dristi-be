"""Moving a hearing that has not been heard, singly and in bulk (spec 0023 #8, #11.4)."""

import datetime
from unittest import mock

import dramatiq
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.hearings import errors, tasks
from apps.hearings.enums import (
    BulkItemResult,
    BulkMode,
    BulkRescheduleStatus,
    CalendarEntryType,
    HearingStatus,
    RescheduleReason,
)
from apps.hearings.models import BulkRescheduleJob, CourtCalendarEntry, HearingDateChange
from apps.hearings.services import calendar, listing, reschedule
from apps.hearings.services import courtroom as court_service
from apps.messaging.models import MessageLog

from .factories import (
    FRI,
    MON,
    SAT,
    SUN,
    THU,
    TODAY,
    TUE,
    WED,
    code,
    field,
    hold,
    schedule,
    set_config,
)

pytestmark = pytest.mark.django_db


def move(hearing, date, reason=RescheduleReason.NOT_REACHED, **kwargs):
    return reschedule.reschedule(
        hearing_id=hearing.pk, hearing_date=date, reason_code=reason, **kwargs
    )


class TestSingleMove:
    def test_moves_in_place_and_logs(self, case, staff, django_capture_on_commit_callbacks):
        hearing = schedule(case, MON)
        with django_capture_on_commit_callbacks(execute=True):
            result = move(
                hearing,
                WED,
                RescheduleReason.PRESIDING_OFFICER_ON_LEAVE,
                reason_text="Leave",
                actor=staff,
            )
        moved = result.hearing
        assert (moved.pk, moved.hearing_date, moved.reschedule_count, moved.original_date) == (
            hearing.pk,
            WED,
            1,
            MON,
        )
        change = HearingDateChange.objects.get(hearing=hearing)
        assert (change.source, change.sought_by, change.reason_text, change.source_ref) == (
            "COURT_ADMIN",
            "COURT",
            "Leave",
            None,
        )
        assert (
            moved.history.first().history_change_reason == "COURT_ADMIN Presiding officer on leave"
        )
        assert MessageLog.objects.filter(
            correlation_id=f"hearing:{case.pk}", message_key="HEARING_RESCHEDULED"
        ).exists()

    @pytest.mark.parametrize(
        "reason", [RescheduleReason.PARTY_APPLICATION, RescheduleReason.JUDICIAL_DIRECTION]
    )
    def test_order_only_reasons(self, case, reason):
        with pytest.raises(BusinessError) as excinfo:
            move(schedule(case, MON), WED, reason)
        assert (code(excinfo), field(excinfo)) == ("E10013", "reason_code")

    def test_nothing_to_change(self, case):
        with pytest.raises(BusinessError) as excinfo:
            move(schedule(case, MON), MON)
        assert code(excinfo) == "E10012"

    @pytest.mark.parametrize(
        ("date", "expected"),
        [
            (SUN, "E10006"),
            (TODAY - datetime.timedelta(days=1), "E10005"),
            (TODAY + datetime.timedelta(days=400), "E10007"),
        ],
    )
    def test_invalid_dates(self, case, date, expected):
        with pytest.raises(BusinessError) as excinfo:
            move(schedule(case, MON), date)
        assert (code(excinfo), field(excinfo)) == (expected, "hearing_date")

    def test_purpose_only_keeps_the_serial_number(self, case):
        hearing = schedule(case, MON)
        moved = move(hearing, MON, purpose_code="ARGUMENTS").hearing
        assert (moved.purpose.code, moved.sequence) == ("ARGUMENTS", hearing.sequence)

    def test_retired_purpose(self, case):
        from apps.hearings.models import HearingPurpose

        HearingPurpose.objects.filter(code="MEDIATION").update(is_active=False)
        with pytest.raises(BusinessError) as excinfo:
            move(schedule(case, MON), WED, purpose_code="MEDIATION")
        assert (code(excinfo), field(excinfo)) == ("E10014", "purpose")

    def test_heard_hearing_cannot_move(self, case):
        hearing = schedule(case, TODAY)
        court_service.start(hearing_id=hearing.pk)
        court_service.end(hearing_id=hearing.pk)
        with pytest.raises(BusinessError) as excinfo:
            move(hearing, WED)
        assert code(excinfo) == "E10001"

    def test_abandoned_moved_when_not_reached(self, case):
        hearing = schedule(case, TODAY)
        court_service.end_day(case.court_id, TODAY)
        set_config("business_date_override", MON.isoformat())
        moved = move(hearing, WED).hearing
        assert (moved.status, moved.hearing_date) == (HearingStatus.SCHEDULED, WED)

    def test_abandoned_cannot_be_rescheduled_onto_its_past_date(self, case):
        """A purpose-only move used to schedule it back on the past day (bug)."""
        hearing = schedule(case, TODAY)
        court_service.end_day(case.court_id, TODAY)
        set_config("business_date_override", MON.isoformat())
        with pytest.raises(BusinessError) as excinfo:
            move(hearing, TODAY, purpose_code="ARGUMENTS")
        assert code(excinfo) == "E10005"

    def test_case_already_scheduled(self, case):
        abandoned = schedule(case, TODAY)
        court_service.end_day(case.court_id, TODAY)
        set_config("business_date_override", MON.isoformat())
        schedule(case, TUE)
        with pytest.raises(BusinessError) as excinfo:
            move(abandoned, WED)
        assert code(excinfo) == "E10004"

    def test_capacity(self, case, other_case, third_case):
        schedule(other_case, WED)
        schedule(third_case, FRI)
        set_config("max_hearings_per_day", "1")
        hearing = schedule(case, MON)
        assert [w.code for w in move(hearing, WED).warnings] == ["COURT_DAY_FULL"]
        set_config("capacity_mode", "block")
        with pytest.raises(BusinessError) as excinfo:
            move(hearing, FRI)
        assert (code(excinfo), field(excinfo)) == ("E10009", "hearing_date")

    def test_adjournment_warning_names_the_party_never_blocks(self, case):
        first = schedule(case, TODAY)
        court_service.start(hearing_id=first.pk)
        court_service.end(hearing_id=first.pk, adjournment_sought_by="ACCUSED")
        set_config("adjournment_warning_threshold", "1")
        result = move(schedule(case, MON), WED)
        assert [(w.code, w.detail) for w in result.warnings] == [
            ("ADJOURNMENT_LIMIT_REACHED", {"side": "ACCUSED", "count": 1})
        ]

    def test_stale(self, case):
        hearing = schedule(case, MON)
        with pytest.raises(BusinessError) as excinfo:
            move(
                hearing, WED, if_unmodified_since=hearing.updated_at - datetime.timedelta(seconds=5)
            )
        assert code(excinfo) == "E10002"


def preview(court, hearings, **kwargs):
    defaults = {
        "mode": BulkMode.TO_DATE,
        "target_date": FRI,
        "reason_code": RescheduleReason.PRESIDING_OFFICER_ON_LEAVE,
    }
    return reschedule.preview_bulk(
        court_id=court.pk, hearing_ids=[h.pk for h in hearings], **{**defaults, **kwargs}
    )


def run(job, actor):
    """Confirm, then run the job as the worker would."""
    reschedule.confirm_bulk(job_id=job.pk, actor=actor)
    return reschedule.run_bulk(job.pk)


class TestBulkPreview:
    def test_preview_changes_nothing(self, courtroom, case, other_case):
        hearings = [schedule(case, MON), schedule(other_case, MON)]
        stamps = [h.updated_at for h in hearings]
        result = preview(courtroom, hearings)
        assert result.job.status == BulkRescheduleStatus.PREVIEWED
        assert [(line["from_date"], line["to_date"]) for line in result.lines] == [
            (MON, FRI),
            (MON, FRI),
        ]
        assert result.loads == [
            {"date": FRI, "capacity": 40, "provisional": 0, "listed_before": 0, "listed_after": 2}
        ]
        for hearing, stamp in zip(hearings, stamps, strict=True):
            hearing.refresh_from_db()
            assert (hearing.hearing_date, hearing.updated_at) == (MON, stamp)

    def test_next_available_respects_free_capacity_and_order(
        self, courtroom, case, other_case, third_case
    ):
        set_config("max_hearings_per_day", "2")
        hearings = [schedule(case, MON), schedule(other_case, MON), schedule(third_case, TUE)]
        calendar.create_entry(
            court_id=courtroom.pk, date=THU, entry_type=CalendarEntryType.HOLIDAY, reason="x"
        )
        result = preview(
            courtroom, hearings, mode=BulkMode.NEXT_AVAILABLE, target_date=None, schedule_after=WED
        )
        targets = [line["to_date"] for line in result.lines]
        assert targets == [FRI, FRI, SAT]

    def test_holds_take_free_places(self, courtroom, case, other_case, third_case):
        set_config("max_hearings_per_day", "1")
        hold(third_case, FRI)
        result = preview(
            courtroom,
            [schedule(case, MON)],
            mode=BulkMode.NEXT_AVAILABLE,
            target_date=None,
            schedule_after=THU,
        )
        assert [line["to_date"] for line in result.lines] == [SAT]

    def test_refusals(self, courtroom, case, foreign_court):
        hearing = schedule(case, MON)
        cases = [
            ({"reason_code": RescheduleReason.PARTY_APPLICATION}, "E10013"),
            ({"target_date": SUN}, "E10006"),
            ({"target_date": MON}, "E10012"),
            ({"target_date": None}, "E00001"),
            ({"mode": BulkMode.NEXT_AVAILABLE, "target_date": None}, "E00001"),
            ({"mode": "SOMEDAY"}, "E00001"),
        ]
        for kwargs, expected in cases:
            with pytest.raises(BusinessError) as excinfo:
                preview(courtroom, [hearing], **kwargs)
            assert code(excinfo) == expected, kwargs
        with pytest.raises(BusinessError) as excinfo:
            preview(foreign_court, [hearing])
        assert code(excinfo) == "E00105"
        with pytest.raises(BusinessError):
            reschedule.preview_bulk(
                court_id=courtroom.pk,
                hearing_ids=[],
                mode=BulkMode.TO_DATE,
                target_date=FRI,
                reason_code="NOT_REACHED",
            )
        assert not BulkRescheduleJob.objects.exists()

    def test_too_many(self, courtroom, case, other_case):
        set_config("bulk_max_hearings", "1")
        with pytest.raises(BusinessError) as excinfo:
            preview(courtroom, [schedule(case, MON), schedule(other_case, MON)])
        assert code(excinfo) == "E10024"

    def test_heard_hearing_refused(self, courtroom, case):
        hearing = schedule(case, TODAY)
        court_service.start(hearing_id=hearing.pk)
        court_service.end(hearing_id=hearing.pk)
        with pytest.raises(BusinessError) as excinfo:
            preview(courtroom, [hearing])
        assert code(excinfo) == "E10001"

    def test_same_hearing_three_ways_is_one_item(self, courtroom, case):
        hearing = schedule(case, MON)
        result = reschedule.preview_bulk(
            court_id=courtroom.pk,
            hearing_ids=[hearing.pk, str(hearing.pk), str(hearing.pk).upper()],
            mode=BulkMode.TO_DATE,
            target_date=FRI,
            reason_code="NOT_REACHED",
        )
        assert result.job.items.count() == 1

    def test_schedule_after_beyond_the_horizon(self, courtroom, case):
        hearing = schedule(case, MON)
        set_config("max_days_ahead", "30")
        with pytest.raises(BusinessError) as excinfo:
            preview(
                courtroom,
                [hearing],
                mode=BulkMode.NEXT_AVAILABLE,
                target_date=None,
                schedule_after=TODAY + datetime.timedelta(days=30),
            )
        assert (code(excinfo), field(excinfo)) == ("E10007", "schedule_after")
        assert not BulkRescheduleJob.objects.exists()

    def test_not_enough_free_places_before_the_horizon(self, courtroom, case, other_case):
        hearings = [schedule(case, MON), schedule(other_case, MON)]
        set_config("max_hearings_per_day", "1")
        set_config("max_days_ahead", "1")
        with pytest.raises(BusinessError) as excinfo:
            preview(
                courtroom,
                hearings,
                mode=BulkMode.NEXT_AVAILABLE,
                target_date=None,
                schedule_after=TODAY,
            )
        assert code(excinfo) == "E10007"
        assert not BulkRescheduleJob.objects.exists()


class TestBulkRun:
    def test_confirm_and_run(
        self, courtroom, case, other_case, setter, django_capture_on_commit_callbacks
    ):
        hearings = [schedule(case, MON), schedule(other_case, MON)]
        job = preview(courtroom, hearings, block_source_dates=True).job
        with django_capture_on_commit_callbacks(execute=True):
            job = run(job, setter)
        assert job.status == BulkRescheduleStatus.COMPLETED
        assert set(job.items.values_list("result", flat=True)) == {BulkItemResult.MOVED}
        for hearing in hearings:
            hearing.refresh_from_db()
            assert hearing.hearing_date == FRI
        change = HearingDateChange.objects.filter(hearing=hearings[0]).get()
        assert (change.source, change.source_ref) == ("BULK", job.pk)
        entry = CourtCalendarEntry.objects.get(court=courtroom, date=MON)
        assert entry.entry_type == CalendarEntryType.PRESIDING_OFFICER_LEAVE
        for c in (case, other_case):
            assert MessageLog.objects.filter(
                correlation_id=f"hearing:{c.pk}", message_key="HEARING_RESCHEDULED"
            ).exists()

    def test_confirm_twice_and_expired(self, courtroom, case, other_case, setter):
        job = preview(courtroom, [schedule(case, MON)]).job
        reschedule.confirm_bulk(job_id=job.pk, actor=setter)
        with pytest.raises(BusinessError) as excinfo:
            reschedule.confirm_bulk(job_id=job.pk, actor=setter)
        assert code(excinfo) == "E10016"
        stale = preview(courtroom, [schedule(other_case, TUE)]).job
        BulkRescheduleJob.objects.filter(pk=stale.pk).update(
            preview_expires_at=timezone.now() - datetime.timedelta(seconds=1)
        )
        with pytest.raises(BusinessError) as excinfo:
            reschedule.confirm_bulk(job_id=stale.pk, actor=setter)
        assert code(excinfo) == "E10015"
        assert reschedule.expire_previews() == 1
        stale.refresh_from_db()
        assert stale.status == BulkRescheduleStatus.EXPIRED

    def test_skips_and_failures(self, courtroom, case, other_case, third_case, setter):
        started = schedule(case, TODAY)
        changed = schedule(other_case, MON)
        failing = schedule(third_case, TUE)
        job = preview(courtroom, [started, changed, failing]).job
        court_service.start(hearing_id=started.pk)
        listing.attach_order(hearing_id=changed.pk, order_id="5d9d9d9d-9d9d-4d9d-9d9d-9d9d9d9d9d9d")
        CourtCalendarEntry.objects.create(
            court=courtroom, date=FRI, entry_type=CalendarEntryType.HOLIDAY, reason="Declared"
        )
        job = run(job, setter)
        results = {item.hearing_id: (item.result, item.error_code) for item in job.items.all()}
        assert results == {
            started.pk: (BulkItemResult.SKIPPED_STARTED, ""),
            changed.pk: (BulkItemResult.SKIPPED_CHANGED, ""),
            failing.pk: (BulkItemResult.FAILED, "E10006"),
        }
        assert job.status == BulkRescheduleStatus.PARTIALLY_FAILED

    def test_cancelled_after_preview_is_skipped_as_changed(self, courtroom, case, setter):
        hearing = schedule(case, MON)
        job = preview(courtroom, [hearing]).job
        listing.cancel_listed_in_error(hearing_id=hearing.pk)
        job = run(job, setter)
        assert job.items.get().result == BulkItemResult.SKIPPED_CHANGED

    def test_an_unexpected_error_fails_one_item_only(self, courtroom, case, other_case, setter):
        good, bad = schedule(case, MON), schedule(other_case, MON)
        job = preview(courtroom, [good, bad]).job
        real_move = reschedule.move

        def flaky(hearing, **kwargs):
            if hearing.pk == bad.pk:
                raise RuntimeError("database hiccup")
            return real_move(hearing, **kwargs)

        with mock.patch.object(reschedule, "move", flaky):
            job = run(job, setter)
        results = {item.hearing_id: (item.result, item.error_code) for item in job.items.all()}
        assert results == {good.pk: ("MOVED", ""), bad.pk: ("FAILED", "E00100")}

    @pytest.mark.parametrize(
        ("raised", "expected"),
        [
            (lambda: BusinessError(errors.COURT_DAY_FULL), "E10009"),
            (lambda: ValidationError({"to_date": "Not allowed."}), "E00001"),
        ],
    )
    def test_a_refused_move_records_its_error_code(
        self, courtroom, case, other_case, setter, raised, expected
    ):
        good, bad = schedule(case, MON), schedule(other_case, MON)
        job = preview(courtroom, [good, bad]).job
        real_move = reschedule.move

        def refusing(hearing, **kwargs):
            if hearing.pk == bad.pk:
                raise raised()
            return real_move(hearing, **kwargs)

        with mock.patch.object(reschedule, "move", refusing):
            job = run(job, setter)
        results = {item.hearing_id: (item.result, item.error_code) for item in job.items.all()}
        assert results == {good.pk: ("MOVED", ""), bad.pk: ("FAILED", expected)}
        assert job.status == BulkRescheduleStatus.PARTIALLY_FAILED

    def test_case_scheduled_again_after_the_preview(self, courtroom, case, setter):
        abandoned = schedule(case, TODAY)
        court_service.end_day(case.court_id, TODAY)
        set_config("business_date_override", MON.isoformat())
        job = preview(courtroom, [abandoned], target_date=WED).job
        fresh = schedule(case, TUE)
        job = run(job, setter)
        assert (job.items.get().result, job.items.get().error_code) == ("FAILED", "E10004")
        abandoned.refresh_from_db()
        fresh.refresh_from_db()
        assert (abandoned.status, fresh.hearing_date) == (HearingStatus.ABANDONED, TUE)

    def test_blocking_leaves_existing_entries_and_busy_days_alone(
        self, courtroom, case, other_case, third_case, setter
    ):
        moved_from_mon = schedule(case, MON)
        moved_from_tue = schedule(other_case, TUE)
        staying_on_tue = schedule(third_case, TUE)
        calendar.create_entry(
            court_id=courtroom.pk,
            date=MON,
            entry_type=CalendarEntryType.REDUCED_SITTING,
            reason="Half day",
            capacity_override=5,
        )
        job = preview(courtroom, [moved_from_mon, moved_from_tue], block_source_dates=True).job
        job = run(job, setter)
        assert job.status == BulkRescheduleStatus.COMPLETED
        mon = CourtCalendarEntry.objects.get(court=courtroom, date=MON)
        assert (mon.entry_type, mon.reason) == (CalendarEntryType.REDUCED_SITTING, "Half day")
        assert not CourtCalendarEntry.objects.filter(court=courtroom, date=TUE).exists()
        staying_on_tue.refresh_from_db()
        assert staying_on_tue.hearing_date == TUE

    def test_redelivery_finishes_and_never_repeats(self, courtroom, case, other_case, setter):
        first, second = schedule(case, MON), schedule(other_case, MON)
        job = preview(courtroom, [first, second]).job
        reschedule.confirm_bulk(job_id=job.pk, actor=setter)
        BulkRescheduleJob.objects.filter(pk=job.pk).update(status=BulkRescheduleStatus.RUNNING)
        job.refresh_from_db()
        item = job.items.order_by("to_date", "from_date").first()
        result, error, _ = reschedule._move_item(job, item, TODAY)
        item.result = result
        item.save()
        job = reschedule.run_bulk(job.pk)
        assert job.status == BulkRescheduleStatus.COMPLETED
        for hearing in (first, second):
            hearing.refresh_from_db()
            assert hearing.reschedule_count == 1
        assert reschedule.run_bulk(job.pk).status == BulkRescheduleStatus.COMPLETED


class TestTasks:
    def test_confirm_enqueues_the_run(
        self, courtroom, case, setter, django_capture_on_commit_callbacks
    ):
        broker = dramatiq.get_broker()
        broker.flush_all()
        job = preview(courtroom, [schedule(case, MON)]).job
        with django_capture_on_commit_callbacks(execute=True):
            reschedule.confirm_bulk(job_id=job.pk, actor=setter)
        queued = broker.queues["default"].qsize()
        assert queued >= 1
        message = broker.queues["default"].get_nowait()
        assert message is not None

    def test_actors_call_the_services(self, courtroom, case, other_case, setter):
        job = preview(courtroom, [schedule(case, MON)]).job
        reschedule.confirm_bulk(job_id=job.pk, actor=setter)
        tasks.run_bulk_reschedule.fn(str(job.pk))
        job.refresh_from_db()
        assert job.status == BulkRescheduleStatus.COMPLETED
        assert tasks.expire_bulk_previews.fn() == 0
        schedule(other_case, TODAY)
        set_config("business_date_override", MON.isoformat())
        assert tasks.end_hearing_days.fn() == 1
