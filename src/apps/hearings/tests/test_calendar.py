"""Business date, sitting days, capacity and the court calendar (spec 0023 #4, #9)."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.hearings.enums import CalendarEntryType
from apps.hearings.models import CourtCalendarEntry
from apps.hearings.services import calendar

from .factories import FRI, MON, SAT, SUN, TODAY, WED, code, field, hold, schedule, set_config

pytestmark = pytest.mark.django_db


def problems(court, date, **kwargs):
    return [problem.error.code for problem in calendar.date_problems(court.pk, date, **kwargs)]


class TestBusinessDate:
    def test_override_pins_the_date(self):
        assert calendar.business_date() == TODAY

    def test_without_override_it_is_today_in_ist(self, settings):
        set_config("business_date_override", "")
        assert calendar.business_date() == timezone.now().astimezone(calendar.IST).date()

    def test_ist_midnight_boundary(self, monkeypatch):
        """18:31 UTC is already the next day in IST (#4)."""
        set_config("business_date_override", "")
        late = datetime.datetime(2026, 11, 12, 18, 31, tzinfo=datetime.UTC)
        monkeypatch.setattr(calendar.timezone, "now", lambda: late)
        assert calendar.business_date() == datetime.date(2026, 11, 13)

    def test_override_ignored_in_production(self, monkeypatch):
        from apps.hearings import conf

        monkeypatch.setattr(conf, "is_production", lambda: True)
        assert conf.business_date_override() is None

    def test_info(self, courtroom):
        info = calendar.business_date_info(courtroom.pk)
        assert info == {
            "business_date": TODAY,
            "timezone": "Asia/Kolkata",
            "sitting": True,
            "sitting_time": "11:00",
        }

    def test_per_court_sitting_time(self, courtroom):
        set_config(f"sitting_time.{courtroom.code.lower()}", "10:30")
        assert calendar.business_date_info(courtroom.pk)["sitting_time"] == "10:30"


class TestSittingDays:
    def test_sunday_does_not_sit(self, courtroom):
        assert not calendar.is_sitting_day(courtroom.pk, SUN)
        assert calendar.is_sitting_day(courtroom.pk, SAT)

    def test_weekday_config(self, courtroom):
        set_config("non_sitting_weekdays", "SAT,SUN")
        assert not calendar.is_sitting_day(courtroom.pk, SAT)

    @pytest.mark.parametrize(
        "entry_type",
        [
            CalendarEntryType.HOLIDAY,
            CalendarEntryType.PRESIDING_OFFICER_LEAVE,
            CalendarEntryType.NON_SITTING,
        ],
    )
    def test_non_sitting_entries(self, courtroom, entry_type):
        calendar.create_entry(court_id=courtroom.pk, date=MON, entry_type=entry_type, reason="x")
        assert not calendar.is_sitting_day(courtroom.pk, MON)
        assert calendar.day_load(courtroom.pk, MON).capacity == 0

    def test_reduced_sitting_sits_with_its_capacity(self, courtroom):
        calendar.create_entry(
            court_id=courtroom.pk,
            date=MON,
            entry_type=CalendarEntryType.REDUCED_SITTING,
            reason="Half day",
            capacity_override=5,
        )
        load = calendar.day_load(courtroom.pk, MON)
        assert (load.sitting, load.capacity) == (True, 5)

    def test_default_capacity(self, courtroom):
        assert calendar.day_load(courtroom.pk, MON).capacity == 40
        set_config("max_hearings_per_day", "12")
        assert calendar.day_load(courtroom.pk, MON).capacity == 12


class TestDateProblems:
    def test_valid(self, courtroom):
        assert problems(courtroom, TODAY) == []

    def test_past(self, courtroom):
        assert problems(courtroom, TODAY - datetime.timedelta(days=1)) == ["E10005"]

    def test_not_sitting(self, courtroom):
        assert problems(courtroom, SUN) == ["E10006"]

    def test_horizon(self, courtroom):
        assert "E10007" not in problems(courtroom, TODAY + datetime.timedelta(days=365))
        assert "E10007" in problems(courtroom, TODAY + datetime.timedelta(days=366))

    def test_not_after_previous(self, courtroom):
        assert problems(courtroom, MON, previous_date=MON) == ["E10008"]

    def test_messages_name_the_date_and_why(self, courtroom):
        CourtCalendarEntry.objects.create(
            court=courtroom, date=MON, entry_type=CalendarEntryType.HOLIDAY, reason="Onam"
        )
        (holiday,) = calendar.date_problems(courtroom.pk, MON)
        (sunday,) = calendar.date_problems(courtroom.pk, SUN)
        assert holiday.message == (
            "The court does not sit on 16 Nov 2026 (holiday: Onam). Choose a sitting day."
        )
        assert "22 Nov 2026 is a Sunday" in sunday.message


class TestLoad:
    def test_listed_and_provisional_kept_apart(self, courtroom, case, other_case):
        schedule(case, MON)
        hold(other_case, MON)
        load = calendar.day_load(courtroom.pk, MON)
        assert (load.listed, load.provisional, load.free) == (1, 1, 38)

    def test_next_sequence_skips_a_cancelled_number(self, courtroom, case, other_case):
        from apps.hearings.services import listing

        first = schedule(case, MON)
        listing.cancel_listed_in_error(hearing_id=first.pk)
        assert calendar.next_sequence(courtroom.pk, MON) == first.sequence + 1


class TestCalendarView:
    def test_by_purpose_adds_up(self, courtroom, case, other_case, third_case):
        schedule(case, WED, "APPEARANCE")
        schedule(other_case, WED, "ARGUMENTS")
        hold(third_case, WED, "APPEARANCE")
        days = {day["date"]: day for day in calendar.calendar(courtroom.pk, MON, SUN)}
        wednesday = days[WED]
        assert (wednesday["listed"], wednesday["provisional"]) == (2, 1)
        assert wednesday["by_purpose"] == [
            {
                "purpose": {"code": "APPEARANCE", "label": "Appearance"},
                "listed": 1,
                "provisional": 1,
            },
            {"purpose": {"code": "ARGUMENTS", "label": "Arguments"}, "listed": 1, "provisional": 0},
        ]
        assert (days[SUN]["sitting"], days[SUN]["capacity"]) == (False, 0)

    def test_range_is_capped(self, courtroom):
        with pytest.raises(BusinessError) as excinfo:
            calendar.calendar(courtroom.pk, TODAY, TODAY + datetime.timedelta(days=92))
        assert (code(excinfo), field(excinfo)) == ("E00001", "to")

    def test_reversed_range(self, courtroom):
        with pytest.raises(BusinessError):
            calendar.calendar(courtroom.pk, FRI, MON)


class TestEntries:
    def test_past_date_refused(self, courtroom):
        with pytest.raises(BusinessError) as excinfo:
            calendar.create_entry(
                court_id=courtroom.pk,
                date=TODAY - datetime.timedelta(days=1),
                entry_type=CalendarEntryType.HOLIDAY,
                reason="x",
            )
        assert (code(excinfo), field(excinfo)) == ("E10005", "date")

    def test_non_sitting_on_a_busy_day_refused_with_counts(self, courtroom, case, other_case):
        schedule(case, MON)
        hold(other_case, MON)
        with pytest.raises(BusinessError) as excinfo:
            calendar.create_entry(
                court_id=courtroom.pk, date=MON, entry_type=CalendarEntryType.HOLIDAY, reason="x"
            )
        assert code(excinfo) == "E10017"
        assert "1 scheduled hearing and 1 date held in a draft order" in str(excinfo.value.detail)

    def test_reduced_sitting_on_a_busy_day_allowed(self, courtroom, case):
        schedule(case, MON)
        entry = calendar.create_entry(
            court_id=courtroom.pk,
            date=MON,
            entry_type=CalendarEntryType.REDUCED_SITTING,
            reason="x",
            capacity_override=3,
        )
        assert entry.pk

    def test_one_entry_per_date(self, courtroom):
        calendar.create_entry(
            court_id=courtroom.pk, date=MON, entry_type=CalendarEntryType.HOLIDAY, reason="x"
        )
        with pytest.raises(ValidationError):
            calendar.create_entry(
                court_id=courtroom.pk,
                date=MON,
                entry_type=CalendarEntryType.NON_SITTING,
                reason="y",
            )

    def test_delete_makes_the_day_sit_again(self, courtroom, staff):
        entry = calendar.create_entry(
            court_id=courtroom.pk, date=MON, entry_type=CalendarEntryType.HOLIDAY, reason="x"
        )
        calendar.delete_entry(court_id=courtroom.pk, entry_id=entry.pk, actor=staff)
        assert calendar.is_sitting_day(courtroom.pk, MON)

    def test_delete_past_entry_refused(self, courtroom):
        entry = CourtCalendarEntry.objects.create(
            court=courtroom,
            date=TODAY - datetime.timedelta(days=2),
            entry_type=CalendarEntryType.HOLIDAY,
            reason="past",
        )
        with pytest.raises(BusinessError) as excinfo:
            calendar.delete_entry(court_id=courtroom.pk, entry_id=entry.pk)
        assert code(excinfo) == "E10005"

    def test_delete_through_another_court_is_not_found(self, courtroom, sibling_courtroom):
        entry = calendar.create_entry(
            court_id=courtroom.pk, date=MON, entry_type=CalendarEntryType.HOLIDAY, reason="x"
        )
        with pytest.raises(CourtCalendarEntry.DoesNotExist):
            calendar.delete_entry(court_id=sibling_courtroom.pk, entry_id=entry.pk)
