"""Model-level rules that hold however a row is written (spec 0023 #2).

The services check these first; the models refuse them again so admin, the
shell or a later service cannot break them.
"""

import datetime
import uuid

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.cases.selectors import get_attendance_roll
from apps.hearings.enums import (
    AttendanceMark,
    BulkMode,
    BulkRescheduleStatus,
    CalendarEntryType,
    ChangeSource,
    RescheduleReason,
    Side,
)
from apps.hearings.models import (
    BulkRescheduleJob,
    CourtCalendarEntry,
    HearingAttendance,
    HearingDateChange,
    HearingPurpose,
)
from apps.hearings.services import courtroom, reschedule

from .factories import FRI, MON, TODAY, WED, schedule

pytestmark = pytest.mark.django_db


def errors_of(excinfo):
    return excinfo.value.message_dict


class TestHearingPurpose:
    def test_code_must_be_upper_snake_case(self):
        with pytest.raises(ValidationError) as excinfo:
            HearingPurpose.objects.create(code="site-visit", label="Site visit", sequence=99)
        assert "code" in errors_of(excinfo)

    def test_code_cannot_be_renamed(self):
        purpose = HearingPurpose.objects.get(code="APPEARANCE")
        purpose.code = "FIRST_APPEARANCE"
        with pytest.raises(ValidationError) as excinfo:
            purpose.save()
        assert "code" in errors_of(excinfo)
        with pytest.raises(ValidationError):
            HearingPurpose.objects.filter(pk=purpose.pk).update(code="FIRST_APPEARANCE")
        assert HearingPurpose.objects.filter(code="APPEARANCE").exists()

    def test_label_can_change(self):
        purpose = HearingPurpose.objects.get(code="APPEARANCE")
        purpose.label = "First appearance"
        purpose.save()
        HearingPurpose.objects.filter(pk=purpose.pk).update(sequence=50)
        purpose.refresh_from_db()
        assert (purpose.label, purpose.sequence) == ("First appearance", 50)

    def test_never_deleted(self):
        purpose = HearingPurpose.objects.get(code="APPEARANCE")
        with pytest.raises(ValidationError):
            purpose.delete()
        with pytest.raises(ValidationError):
            HearingPurpose.objects.filter(pk=purpose.pk).delete()
        assert HearingPurpose.objects.filter(pk=purpose.pk).exists()


class TestHearingAttendance:
    def line(self, hearing, entry, mark=AttendanceMark.PRESENT, mode="IN_PERSON"):
        return HearingAttendance(
            hearing=hearing,
            attendee_type=entry.type,
            participant_id=entry.participant_id,
            mark=mark,
            appearance_mode=mode,
        )

    @pytest.fixture
    def running(self, case):
        return courtroom.start(hearing_id=schedule(case, TODAY).pk)

    def test_valid_mark_saves(self, case, running):
        entry = get_attendance_roll(case.pk)[0]
        self.line(running, entry).save()
        assert HearingAttendance.objects.filter(hearing=running).count() == 1

    @pytest.mark.parametrize(
        ("mark", "mode"),
        [(AttendanceMark.PRESENT, ""), (AttendanceMark.ABSENT, "VIDEO")],
    )
    def test_mode_matches_the_mark(self, case, running, mark, mode):
        entry = get_attendance_roll(case.pk)[0]
        with pytest.raises(ValidationError) as excinfo:
            self.line(running, entry, mark, mode).save()
        assert list(errors_of(excinfo)) == ["appearance_mode"]

    def test_not_before_the_start(self, case):
        hearing = schedule(case, TODAY)
        entry = get_attendance_roll(case.pk)[0]
        with pytest.raises(ValidationError) as excinfo:
            self.line(hearing, entry).save()
        assert list(errors_of(excinfo)) == ["hearing"]

    def test_not_on_the_roll(self, case, running):
        stranger = HearingAttendance(
            hearing=running,
            attendee_type="COMPLAINANT",
            participant_id=uuid.uuid4(),
            mark=AttendanceMark.ABSENT,
        )
        with pytest.raises(ValidationError) as excinfo:
            stranger.save()
        assert list(errors_of(excinfo)) == ["participant_id"]

    def test_locked_marks_cannot_be_added_or_removed(self, case, running):
        roll = get_attendance_roll(case.pk)
        courtroom.set_attendance(
            hearing_id=running.pk,
            marks=[
                {
                    "attendee_type": entry.type,
                    "participant_id": entry.participant_id,
                    "mark": AttendanceMark.ABSENT,
                }
                for entry in roll[:2]
            ],
        )
        courtroom.end(hearing_id=running.pk)
        locked = courtroom.lock_attendance(running.pk)
        with pytest.raises(ValidationError) as excinfo:
            self.line(locked, roll[2]).save()
        assert "hearing" in errors_of(excinfo)
        row = HearingAttendance.objects.filter(hearing=locked).first()
        with pytest.raises(ValidationError):
            row.delete()
        with pytest.raises(ValidationError):
            HearingAttendance.objects.filter(hearing=locked).delete()
        assert HearingAttendance.objects.filter(hearing=locked).count() == 2


class TestHearingDateChange:
    def entry(self, hearing, **kwargs):
        return HearingDateChange(
            **{
                "hearing": hearing,
                "from_date": hearing.hearing_date,
                "to_date": WED,
                "from_purpose": hearing.purpose,
                "to_purpose": hearing.purpose,
                "reason_code": RescheduleReason.NOT_REACHED,
                "sought_by": Side.COURT,
                "source": ChangeSource.COURT_ADMIN,
                **kwargs,
            }
        )

    def test_append_only(self, case):
        hearing = schedule(case, MON)
        reschedule.reschedule(
            hearing_id=hearing.pk, hearing_date=WED, reason_code=RescheduleReason.NOT_REACHED
        )
        change = HearingDateChange.objects.get(hearing=hearing)
        change.reason_text = "Edited later"
        with pytest.raises(ValidationError):
            change.save()
        with pytest.raises(ValidationError):
            change.delete()
        with pytest.raises(ValidationError):
            HearingDateChange.objects.filter(pk=change.pk).update(reason_text="Edited later")
        with pytest.raises(ValidationError):
            HearingDateChange.objects.filter(pk=change.pk).delete()
        change.refresh_from_db()
        assert change.reason_text == ""

    def test_must_match_the_hearing_before_the_move(self, case):
        hearing = schedule(case, MON)
        other_purpose = HearingPurpose.objects.get(code="ARGUMENTS")
        with pytest.raises(ValidationError) as excinfo:
            self.entry(hearing, from_date=FRI, from_purpose=other_purpose).save()
        assert set(errors_of(excinfo)) == {"from_date", "from_purpose"}

    def test_heard_hearing_cannot_be_logged_as_moved(self, case):
        hearing = courtroom.start(hearing_id=schedule(case, TODAY).pk)
        courtroom.end(hearing_id=hearing.pk)
        hearing.refresh_from_db()
        with pytest.raises(ValidationError) as excinfo:
            self.entry(hearing).save()
        assert "hearing" in errors_of(excinfo)

    def test_bulk_create_validates_each_entry(self, case, other_case):
        good = schedule(case, MON)
        stale = schedule(other_case, MON)
        with pytest.raises(ValidationError):
            HearingDateChange.objects.bulk_create(
                [self.entry(good), self.entry(stale, from_date=FRI)]
            )
        assert not HearingDateChange.objects.exists()
        HearingDateChange.objects.bulk_create([self.entry(good)])
        assert HearingDateChange.objects.filter(hearing=good).count() == 1


class TestBulkRescheduleJob:
    def job(self, courtroom):
        return BulkRescheduleJob.objects.create(
            court=courtroom,
            mode=BulkMode.TO_DATE,
            target_date=FRI,
            reason_code=RescheduleReason.PRESIDING_OFFICER_ON_LEAVE,
            preview_expires_at=timezone.now() + datetime.timedelta(minutes=10),
        )

    def test_unconfirmed_preview_can_be_deleted(self, courtroom):
        self.job(courtroom).delete()
        expired = self.job(courtroom)
        expired.status = BulkRescheduleStatus.EXPIRED
        expired.save()
        BulkRescheduleJob.objects.filter(pk=expired.pk).delete()
        assert not BulkRescheduleJob.objects.exists()

    def test_confirmed_job_is_never_deleted(self, courtroom, case, setter):
        job = reschedule.preview_bulk(
            court_id=courtroom.pk,
            hearing_ids=[schedule(case, MON).pk],
            mode=BulkMode.TO_DATE,
            target_date=FRI,
            reason_code=RescheduleReason.PRESIDING_OFFICER_ON_LEAVE,
        ).job
        job = reschedule.confirm_bulk(job_id=job.pk, actor=setter)
        with pytest.raises(ValidationError):
            job.delete()
        with pytest.raises(ValidationError):
            BulkRescheduleJob.objects.filter(pk=job.pk).delete()
        assert BulkRescheduleJob.objects.filter(pk=job.pk).exists()


class TestCourtCalendarEntry:
    """The admin form reports a capacity mismatch on the capacity field."""

    @pytest.mark.parametrize(
        ("entry_type", "capacity"),
        [
            (CalendarEntryType.REDUCED_SITTING, None),
            (CalendarEntryType.REDUCED_SITTING, 0),
            (CalendarEntryType.HOLIDAY, 10),
        ],
    )
    def test_capacity_matches_the_entry_type(self, courtroom, entry_type, capacity):
        entry = CourtCalendarEntry(
            court=courtroom,
            date=MON,
            entry_type=entry_type,
            reason="Onam",
            capacity_override=capacity,
        )
        with pytest.raises(ValidationError) as excinfo:
            entry.save()
        assert "capacity_override" in errors_of(excinfo)
