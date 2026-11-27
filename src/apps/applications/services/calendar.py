"""Working days (spec 0033 #6.9, ``ALC-03``).

PLACEHOLDER for ``apps.core.services.calendar.next_working_day`` (#1.2): the
next day court **staff work**, not the next day the court sits. A non-working
weekday (``applications.<state>.non_working_weekdays``, default Sunday) or a
court ``HOLIDAY`` entry (0023) is skipped; a presiding officer's leave, a
non-sitting day and a reduced sitting are working days.
"""

import datetime

from apps.hearings.enums import CalendarEntryType
from apps.hearings.models import CourtCalendarEntry
from apps.hearings.services.calendar import business_date

from .. import conf

MAX_LOOKAHEAD_DAYS = 366


def next_working_day(court_id, day, *, state_code=""):
    """The first working day after ``day`` at ``court_id``."""
    weekdays = conf.non_working_weekdays(state_code)
    horizon = day + datetime.timedelta(days=MAX_LOOKAHEAD_DAYS)
    holidays = set(
        CourtCalendarEntry.objects.filter(
            court_id=court_id,
            entry_type=CalendarEntryType.HOLIDAY,
            date__gt=day,
            date__lte=horizon,
        ).values_list("date", flat=True)
    )
    candidate = day + datetime.timedelta(days=1)
    while candidate <= horizon:
        if candidate.weekday() not in weekdays and candidate not in holidays:
            return candidate
        candidate += datetime.timedelta(days=1)
    return day + datetime.timedelta(days=1)


def today():
    """The court's business date (0023 #4), shared so tests pin one clock."""
    return business_date()
