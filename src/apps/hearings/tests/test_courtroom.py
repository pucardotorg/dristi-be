"""Running the courtroom: start, pass over, end, bulk, attendance, board, sweep (spec 0023 #5, #6)."""

import datetime
import uuid

import pytest
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.cases.selectors import get_attendance_roll
from apps.hearings.enums import HearingStatus
from apps.hearings.models import HearingAttendance
from apps.hearings.services import courtroom

from .factories import MON, TODAY, code, field, make_case, schedule, set_config

pytestmark = pytest.mark.django_db


def mark(entry, value="PRESENT", mode="IN_PERSON"):
    return {
        "attendee_type": entry.type,
        "participant_id": entry.participant_id,
        "mark": value,
        "appearance_mode": mode if value == "PRESENT" else "",
    }


class TestStartPassOverEnd:
    def test_start(self, case, staff):
        hearing = courtroom.start(hearing_id=schedule(case, TODAY).pk, actor=staff)
        assert hearing.status == HearingStatus.IN_PROGRESS
        assert hearing.started_at == hearing.last_started_at
        assert hearing.history.first().history_change_reason == "started"
        assert hearing.history.first().history_user_id == staff.pk

    def test_start_only_on_its_day(self, case):
        hearing = schedule(case, MON)
        with pytest.raises(BusinessError) as excinfo:
            courtroom.start(hearing_id=hearing.pk)
        assert code(excinfo) == "E10010"
        assert "16 Nov 2026" in str(excinfo.value.detail)

    def test_several_in_progress_in_one_court(self, case, other_case):
        for c in (case, other_case):
            courtroom.start(hearing_id=schedule(c, TODAY).pk)
        assert case.court.hearings.filter(status=HearingStatus.IN_PROGRESS).count() == 2

    def test_pass_over_and_restart_sum_heard_time(self, case, monkeypatch):
        clock = [timezone.now()]
        monkeypatch.setattr(courtroom.timezone, "now", lambda: clock[0])
        hearing = schedule(case, TODAY)
        courtroom.start(hearing_id=hearing.pk)
        first_start = clock[0]
        clock[0] += datetime.timedelta(minutes=10)
        passed = courtroom.pass_over(hearing_id=hearing.pk)
        assert (passed.status, passed.heard_duration, passed.last_started_at) == (
            HearingStatus.PASSED_OVER,
            datetime.timedelta(minutes=10),
            None,
        )
        clock[0] += datetime.timedelta(minutes=30)
        restarted = courtroom.start(hearing_id=hearing.pk)
        assert restarted.started_at == first_start
        clock[0] += datetime.timedelta(minutes=5)
        ended = courtroom.end(hearing_id=hearing.pk, adjournment_sought_by="ACCUSED")
        assert ended.heard_duration == datetime.timedelta(minutes=15)
        assert (ended.status, ended.adjournment_sought_by) == (HearingStatus.COMPLETED, "ACCUSED")

    def test_end_starts_nothing_else(self, case, other_case):
        first = schedule(case, TODAY)
        second = schedule(other_case, TODAY)
        courtroom.start(hearing_id=first.pk)
        courtroom.end(hearing_id=first.pk)
        second.refresh_from_db()
        assert second.status == HearingStatus.SCHEDULED

    def test_disallowed_transitions_carry_allowed_actions(self, case):
        hearing = schedule(case, TODAY)
        with pytest.raises(BusinessError) as excinfo:
            courtroom.end(hearing_id=hearing.pk)
        assert code(excinfo) == "E10001"
        assert excinfo.value.allowed_actions == ["start", "pass_over", "reschedule", "cancel"]
        assert "It can be started, passed over, moved or cancelled." in str(excinfo.value.detail)

    def test_heard_is_terminal(self, case):
        hearing = schedule(case, TODAY)
        courtroom.start(hearing_id=hearing.pk)
        courtroom.end(hearing_id=hearing.pk)
        for action in (courtroom.start, courtroom.pass_over, courtroom.end):
            with pytest.raises(BusinessError) as excinfo:
                action(hearing_id=hearing.pk)
            assert code(excinfo) == "E10001"

    def test_stale_write(self, case):
        hearing = schedule(case, TODAY)
        with pytest.raises(BusinessError) as excinfo:
            courtroom.start(
                hearing_id=hearing.pk,
                if_unmodified_since=hearing.updated_at - datetime.timedelta(seconds=5),
            )
        assert code(excinfo) == "E10002"
        assert courtroom.start(
            hearing_id=hearing.pk, if_unmodified_since=hearing.updated_at
        ).status == (HearingStatus.IN_PROGRESS)

    def test_other_court(self, case, sibling_courtroom):
        hearing = schedule(case, TODAY)
        with pytest.raises(type(hearing).DoesNotExist):
            courtroom.start(hearing_id=hearing.pk, court_id=sibling_courtroom.pk)


class TestBulk:
    def test_end_and_skips(self, case, other_case, third_case):
        waiting = schedule(case, TODAY)
        running = schedule(other_case, TODAY)
        courtroom.start(hearing_id=running.pk)
        future = schedule(third_case, MON)
        ghost = uuid.uuid4()
        result = courtroom.bulk_action(
            court_id=case.court_id,
            hearing_ids=[waiting.pk, running.pk, future.pk, ghost],
            action="END",
        )
        assert {d["hearing_id"] for d in result.done} == {waiting.pk, running.pk}
        assert {str(s["hearing_id"]): s["code"] for s in result.skipped} == {
            str(future.pk): "E10010",
            str(ghost): "E00105",
        }
        waiting.refresh_from_db()
        assert waiting.started_at == waiting.ended_at
        assert waiting.heard_duration == datetime.timedelta(0)

    def test_pass_over(self, case, other_case):
        waiting = schedule(case, TODAY)
        heard = schedule(other_case, TODAY)
        courtroom.start(hearing_id=heard.pk)
        courtroom.end(hearing_id=heard.pk)
        result = courtroom.bulk_action(
            court_id=case.court_id, hearing_ids=[waiting.pk, heard.pk], action="PASS_OVER"
        )
        assert [d["hearing_id"] for d in result.done] == [waiting.pk]
        assert result.skipped[0]["code"] == "E10001"

    def test_unknown_action(self, case):
        with pytest.raises(BusinessError) as excinfo:
            courtroom.bulk_action(court_id=case.court_id, hearing_ids=[], action="START")
        assert field(excinfo) == "action"


class TestAttendance:
    @pytest.fixture
    def running(self, case):
        hearing = schedule(case, TODAY)
        return courtroom.start(hearing_id=hearing.pk)

    def test_roll_has_parties_and_advocate_lines(self, case):
        types = [entry.type for entry in get_attendance_roll(case.pk)]
        assert types == ["COMPLAINANT", "COMPLAINANT_ADVOCATE", "ACCUSED"]

    def test_not_before_the_start(self, case):
        hearing = schedule(case, TODAY)
        with pytest.raises(BusinessError) as excinfo:
            courtroom.set_attendance(hearing_id=hearing.pk, marks=[])
        assert code(excinfo) == "E10022"
        assert "once the hearing has started" in str(excinfo.value.detail)

    def test_full_replace_and_complete(self, case, running):
        roll = get_attendance_roll(case.pk)
        courtroom.set_attendance(hearing_id=running.pk, marks=[mark(roll[0])])
        assert courtroom.attendance_complete(running.pk) is False
        courtroom.set_attendance(
            hearing_id=running.pk,
            marks=[mark(roll[0], mode="VIDEO"), mark(roll[1]), mark(roll[2], "NOT_REQUIRED")],
        )
        assert courtroom.attendance_complete(running.pk) is True
        courtroom.set_attendance(hearing_id=running.pk, marks=[mark(roll[2], "ABSENT")])
        assert HearingAttendance.objects.filter(hearing=running).count() == 1

    def test_not_on_roll(self, case, running):
        roll = get_attendance_roll(case.pk)
        stranger = {
            "attendee_type": "COMPLAINANT",
            "participant_id": uuid.uuid4(),
            "mark": "ABSENT",
        }
        with pytest.raises(BusinessError) as excinfo:
            courtroom.set_attendance(hearing_id=running.pk, marks=[mark(roll[0]), stranger])
        assert (code(excinfo), field(excinfo)) == ("E10011", "marks[1]")
        wrong_line = {**mark(roll[2], "ABSENT"), "attendee_type": "ACCUSED_ADVOCATE"}
        with pytest.raises(BusinessError):
            courtroom.set_attendance(hearing_id=running.pk, marks=[wrong_line])

    def test_mode_only_with_present(self, case, running):
        roll = get_attendance_roll(case.pk)
        with pytest.raises(BusinessError) as excinfo:
            courtroom.set_attendance(
                hearing_id=running.pk, marks=[{**mark(roll[0]), "appearance_mode": ""}]
            )
        assert field(excinfo) == "marks[0].appearance_mode"
        with pytest.raises(BusinessError):
            courtroom.set_attendance(
                hearing_id=running.pk,
                marks=[{**mark(roll[0], "ABSENT"), "appearance_mode": "VIDEO"}],
            )

    def test_duplicate(self, case, running):
        roll = get_attendance_roll(case.pk)
        with pytest.raises(BusinessError):
            courtroom.set_attendance(
                hearing_id=running.pk, marks=[mark(roll[0]), mark(roll[0], "ABSENT")]
            )

    def test_heard_hearing_until_locked(self, case, running):
        roll = get_attendance_roll(case.pk)
        courtroom.end(hearing_id=running.pk)
        courtroom.set_attendance(hearing_id=running.pk, marks=[mark(entry) for entry in roll])
        locked = courtroom.lock_attendance(running.pk)
        assert courtroom.lock_attendance(running.pk).attendance_locked_at == (
            locked.attendance_locked_at
        )
        with pytest.raises(BusinessError) as excinfo:
            courtroom.set_attendance(hearing_id=running.pk, marks=[])
        assert code(excinfo) == "E10022"
        assert "locked" in str(excinfo.value.detail)
        assert HearingAttendance.objects.filter(hearing=running).count() == len(roll)


class TestBoard:
    def test_ordered_by_status_then_sequence(self, case, other_case, third_case):
        first, second, third = (schedule(c, TODAY) for c in (case, other_case, third_case))
        courtroom.start(hearing_id=third.pk)
        courtroom.pass_over(hearing_id=first.pk)
        assert [h.pk for h in courtroom.board(case.court_id, TODAY)] == [
            third.pk,
            second.pk,
            first.pk,
        ]

    def test_reorder(self, case, other_case, third_case):
        first, second, third = (schedule(c, TODAY) for c in (case, other_case, third_case))
        courtroom.reorder_board(
            court_id=case.court_id,
            hearing_date=TODAY,
            hearing_ids=[str(third.pk).upper(), first.pk, second.pk],
        )
        for hearing in (first, second, third):
            hearing.refresh_from_db()
        assert (third.sequence, first.sequence, second.sequence) == (1, 2, 3)

    def test_reorder_with_a_heard_hearing_holding_a_higher_number(
        self, case, other_case, third_case
    ):
        """Parking above the waiting rows only used to collide with a heard one (bug)."""
        first, second = schedule(case, TODAY), schedule(other_case, TODAY)
        heard = schedule(third_case, TODAY)
        courtroom.bulk_action(court_id=case.court_id, hearing_ids=[heard.pk], action="END")
        courtroom.reorder_board(
            court_id=case.court_id, hearing_date=TODAY, hearing_ids=[second.pk, first.pk]
        )
        heard.refresh_from_db()
        assert heard.sequence == 3

    @pytest.mark.parametrize("kind", ["partial", "foreign", "duplicate", "malformed"])
    def test_reorder_mismatch(self, case, other_case, third_case, kind):
        first, second = schedule(case, TODAY), schedule(other_case, TODAY)
        elsewhere = schedule(third_case, MON)
        ids = {
            "partial": [first.pk],
            "foreign": [first.pk, second.pk, elsewhere.pk],
            "duplicate": [first.pk, first.pk],
            "malformed": ["nope", first.pk],
        }[kind]
        with pytest.raises(BusinessError) as excinfo:
            courtroom.reorder_board(court_id=case.court_id, hearing_date=TODAY, hearing_ids=ids)
        assert code(excinfo) == "E10019"

    def test_current_and_etag(self, case, other_case):
        first = schedule(case, TODAY)
        schedule(other_case, TODAY)
        tag = courtroom.board_etag(case.court_id)
        assert courtroom.board_etag(case.court_id) == tag
        assert courtroom.current(case.court_id) == []
        courtroom.start(hearing_id=first.pk)
        assert courtroom.board_etag(case.court_id) != tag
        assert [h.pk for h in courtroom.current(case.court_id)] == [first.pk]


class TestMidnightSweep:
    def test_unfinished_listings_are_abandoned(self, case, other_case, third_case, monkeypatch):
        waiting = schedule(case, TODAY)
        running = schedule(other_case, TODAY)
        heard = schedule(third_case, TODAY)
        courtroom.start(hearing_id=running.pk)
        courtroom.start(hearing_id=heard.pk)
        courtroom.end(hearing_id=heard.pk)
        later = timezone.now() + datetime.timedelta(minutes=20)
        monkeypatch.setattr(courtroom.timezone, "now", lambda: later)
        assert courtroom.end_day(case.court_id, TODAY) == 2
        for hearing in (waiting, running, heard):
            hearing.refresh_from_db()
        assert waiting.status == running.status == HearingStatus.ABANDONED
        assert running.abandoned_at == later
        assert running.heard_duration >= datetime.timedelta(minutes=20)
        assert heard.status == HearingStatus.COMPLETED
        assert courtroom.end_day(case.court_id, TODAY) == 0

    def test_end_days_catches_up_every_past_day(self, case):
        schedule(case, TODAY)
        set_config("business_date_override", MON.isoformat())
        assert courtroom.end_days() == 1


def test_unknown_hearing_is_not_found():
    with pytest.raises(Exception) as excinfo:
        courtroom.start(hearing_id=uuid.uuid4())
    assert type(excinfo.value).__name__ == "DoesNotExist"


def test_make_case_without_advocate_has_no_advocate_line(courtroom):
    case = make_case(courtroom)
    assert [entry.type for entry in get_attendance_roll(case.pk)] == ["COMPLAINANT", "ACCUSED"]
