"""Business date, sitting days, capacity, load and the court calendar (spec 0023 #4, #5, #9)."""

import datetime
from collections import defaultdict
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.organizations.models import Organization

from .. import conf, errors
from ..enums import BOARD_STATUSES, CalendarEntryType, HearingStatus
from ..models import CourtCalendarEntry, Hearing, HearingPurpose
from .common import SoftWarning, display_date, join_words

IST = ZoneInfo("Asia/Kolkata")
TIMEZONE_NAME = "Asia/Kolkata"
MAX_CALENDAR_DAYS = 92
# A non-sitting entry is refused on a date with these (#9.2).
BLOCKING_STATUSES = (HearingStatus.SCHEDULED, HearingStatus.PASSED_OVER, HearingStatus.PROVISIONAL)
# (one, many): "1 scheduled hearing", "2 dates held in draft orders".
BLOCKING_LABELS = {
    HearingStatus.SCHEDULED: ("scheduled hearing", "scheduled hearings"),
    HearingStatus.PASSED_OVER: ("passed-over hearing", "passed-over hearings"),
    HearingStatus.PROVISIONAL: ("date held in a draft order", "dates held in draft orders"),
}
PAST_ENTRY_MESSAGE = "Calendar entries for past dates cannot be added or removed."


def business_date():
    """Return the court's today: the date in ``Asia/Kolkata``, or the pinned override (#4)."""
    return conf.business_date_override() or timezone.now().astimezone(IST).date()


def lock_court(court_id):
    """Lock the court's row until the transaction ends; serialises its board writes (#11.5)."""
    return Organization.objects.select_for_update().get(pk=court_id)


@dataclass(frozen=True)
class Problem:
    """A rule a date or purpose breaks, with its registered error."""

    error: object
    message: str
    field: str = "hearing_date"

    @classmethod
    def of(cls, error, message=None, field="hearing_date"):
        return cls(error=error, message=message or error.message, field=field)


@dataclass(frozen=True)
class DayLoad:
    """A court's day: whether it sits, its capacity and its load, kept apart (#4, ``NXT-12``)."""

    court_id: object
    date: datetime.date
    sitting: bool
    capacity: int
    listed: int
    provisional: int

    @property
    def free(self):
        """Places left: capacity minus listed minus provisional, never negative."""
        return max(self.capacity - self.listed - self.provisional, 0)

    @property
    def full(self):
        return self.listed + self.provisional >= self.capacity


def _sitting(date, entry, weekdays):
    if date.weekday() in weekdays:
        return False
    return entry is None or entry.entry_type == CalendarEntryType.REDUCED_SITTING


def _capacity(entry, sitting, default):
    if not sitting:
        return 0
    if entry is not None and entry.capacity_override:
        return entry.capacity_override
    return default


def _entries(court_id, date_from, date_to):
    return {
        entry.date: entry
        for entry in CourtCalendarEntry.objects.filter(
            court_id=court_id, date__gte=date_from, date__lte=date_to
        )
    }


def is_sitting_day(court_id, date):
    """Whether the court sits on ``date``: not a non-sitting weekday, and no non-sitting entry."""
    entry = CourtCalendarEntry.objects.filter(court_id=court_id, date=date).first()
    return _sitting(date, entry, conf.non_sitting_weekdays())


def not_sitting_problem(court_id, date):
    """The ``E10006`` problem for ``date``, naming why the court does not sit, or None."""
    entry = CourtCalendarEntry.objects.filter(court_id=court_id, date=date).first()
    if _sitting(date, entry, conf.non_sitting_weekdays()):
        return None
    if entry is not None and entry.entry_type != CalendarEntryType.REDUCED_SITTING:
        message = (
            f"The court does not sit on {display_date(date)} "
            f"({entry.get_entry_type_display().lower()}: {entry.reason}). Choose a sitting day."
        )
    else:
        message = (
            f"{display_date(date)} is a {date:%A}, and the court does not sit on "
            f"{date:%A}s. Choose a sitting day."
        )
    return Problem.of(errors.DATE_NOT_SITTING, message)


def day_loads(court_id, date_from, date_to, exclude_ids=()):
    """Return ``{date: DayLoad}`` for every date in the range. Two queries.

    ``exclude_ids`` leaves hearings out of the counts, e.g. a hold being changed.
    """
    entries = _entries(court_id, date_from, date_to)
    weekdays = conf.non_sitting_weekdays()
    default = conf.max_hearings_per_day()
    counts = (
        Hearing.objects.filter(
            court_id=court_id, hearing_date__gte=date_from, hearing_date__lte=date_to
        )
        .exclude(pk__in=list(exclude_ids))
        .values("hearing_date")
        .annotate(
            listed=Count("pk", filter=Q(status__in=BOARD_STATUSES)),
            provisional=Count("pk", filter=Q(status=HearingStatus.PROVISIONAL)),
        )
    )
    by_date = {row["hearing_date"]: row for row in counts}
    loads = {}
    date = date_from
    while date <= date_to:
        entry = entries.get(date)
        sitting = _sitting(date, entry, weekdays)
        row = by_date.get(date, {})
        loads[date] = DayLoad(
            court_id=court_id,
            date=date,
            sitting=sitting,
            capacity=_capacity(entry, sitting, default),
            listed=row.get("listed", 0),
            provisional=row.get("provisional", 0),
        )
        date += datetime.timedelta(days=1)
    return loads


def day_load(court_id, date, exclude_ids=()):
    """Return the court's ``DayLoad`` for one date."""
    return day_loads(court_id, date, date, exclude_ids)[date]


def date_problems(court_id, date, *, previous_date=None, today=None):
    """Return why ``date`` is not valid for a new or moved hearing, or ``[]`` (#4).

    Valid: a sitting day, not before the business date, at most
    ``max_days_ahead`` after it, and after ``previous_date`` when given.
    """
    today = today or business_date()
    problems = []
    last = today + datetime.timedelta(days=conf.max_days_ahead())
    if date < today:
        problems.append(
            Problem.of(
                errors.DATE_IN_PAST,
                f"{display_date(date)} is in the past. Choose {display_date(today)} or later.",
            )
        )
    elif date > last:
        problems.append(
            Problem.of(
                errors.DATE_BEYOND_HORIZON,
                f"{display_date(date)} is too far ahead. Choose a date up to "
                f"{display_date(last)} ({conf.max_days_ahead()} days from today).",
            )
        )
    not_sitting = not_sitting_problem(court_id, date)
    if not_sitting:
        problems.append(not_sitting)
    if previous_date is not None and date <= previous_date:
        problems.append(
            Problem.of(
                errors.DATE_NOT_AFTER_PREVIOUS,
                f"The date must be after the previous hearing, on {display_date(previous_date)}.",
            )
        )
    return problems


def purpose_problem(purpose_code):
    """Return ``(purpose, None)`` for an active purpose, else ``(None, Problem)`` (``E10014``)."""
    purpose = HearingPurpose.objects.active().filter(code=purpose_code).first()
    if purpose is None:
        return None, Problem.of(errors.PURPOSE_INACTIVE, field="purpose")
    return purpose, None


def capacity_check(court_id, date, exclude_ids=()):
    """Return ``(load, full)`` for adding one hearing to the date, under the court lock (#4)."""
    load = day_load(court_id, date, exclude_ids)
    return load, load.full


def full_day_warning(load):
    """The ``COURT_DAY_FULL`` soft warning for a full day in ``warn`` mode."""
    return SoftWarning(
        code="COURT_DAY_FULL",
        message=(
            f"The court's list for {display_date(load.date)} is full: {load.listed} listed and "
            f"{load.provisional} held in draft orders, against a capacity of {load.capacity}."
        ),
        detail={
            "date": load.date.isoformat(),
            "capacity": load.capacity,
            "listed": load.listed,
            "provisional": load.provisional,
        },
    )


def next_sequence(court_id, date):
    """Return the next serial number on the court's board for the date: ``max + 1`` (#5).

    Call under the court lock. A cancelled hearing keeps its number, so a new
    hearing never takes a number already announced for that day; gaps are kept.
    """
    current = Hearing.objects.filter(
        court_id=court_id,
        hearing_date=date,
        status__in=(*BOARD_STATUSES, HearingStatus.CANCELLED),
    ).aggregate(top=Max("sequence"))["top"]
    return (current or 0) + 1


# Calendar (#9.1)


def calendar(court_id, date_from, date_to):
    """Return one entry per day for the date picker: sitting, capacity, load by purpose (#9.1).

    Three queries for the whole range: entries, purposes, and one grouped count.
    """
    if date_to < date_from:
        raise BusinessError(
            api_errors.INVALID, "The end date must be on or after the start date.", field="to"
        )
    if (date_to - date_from).days + 1 > MAX_CALENDAR_DAYS:
        raise BusinessError(
            api_errors.INVALID,
            f"Ask for at most {MAX_CALENDAR_DAYS} days of the calendar at a time.",
            field="to",
        )
    entries = _entries(court_id, date_from, date_to)
    weekdays = conf.non_sitting_weekdays()
    default = conf.max_hearings_per_day()
    rows = (
        Hearing.objects.filter(
            court_id=court_id,
            hearing_date__gte=date_from,
            hearing_date__lte=date_to,
            status__in=(*BOARD_STATUSES, HearingStatus.PROVISIONAL),
        )
        .values("hearing_date", "purpose_id")
        .annotate(
            listed=Count("pk", filter=Q(status__in=BOARD_STATUSES)),
            provisional=Count("pk", filter=Q(status=HearingStatus.PROVISIONAL)),
        )
    )
    by_date = defaultdict(list)
    purpose_ids = set()
    for row in rows:
        by_date[row["hearing_date"]].append(row)
        purpose_ids.add(row["purpose_id"])
    purposes = {p.pk: p for p in HearingPurpose.objects.filter(pk__in=purpose_ids)}

    days = []
    date = date_from
    while date <= date_to:
        entry = entries.get(date)
        sitting = _sitting(date, entry, weekdays)
        day_rows = sorted(
            by_date.get(date, []),
            key=lambda row: (
                purposes[row["purpose_id"]].sequence,
                purposes[row["purpose_id"]].code,
            ),
        )
        days.append(
            {
                "date": date,
                "sitting": sitting,
                "capacity": _capacity(entry, sitting, default),
                "listed": sum(row["listed"] for row in day_rows),
                "provisional": sum(row["provisional"] for row in day_rows),
                "by_purpose": [
                    {
                        "purpose": {
                            "code": purposes[row["purpose_id"]].code,
                            "label": purposes[row["purpose_id"]].label,
                        },
                        "listed": row["listed"],
                        "provisional": row["provisional"],
                    }
                    for row in day_rows
                ],
                "entry": (
                    {"id": entry.pk, "entry_type": entry.entry_type, "reason": entry.reason}
                    if entry
                    else None
                ),
            }
        )
        date += datetime.timedelta(days=1)
    return days


# Entries (#9.2)


def create_entry(*, court_id, date, entry_type, reason, capacity_override=None, actor=None):
    """Add a non-sitting or reduced-sitting day to the court's calendar (#9.2).

    Refuses a past date (``E10005``), and a non-sitting entry on a date that
    still has scheduled, passed-over or provisional hearings (``E10017``, with
    the counts): those are moved first with a bulk move.
    """
    with transaction.atomic():
        lock_court(court_id)
        if date < business_date():
            raise BusinessError(errors.DATE_IN_PAST, PAST_ENTRY_MESSAGE, field="date")
        if entry_type != CalendarEntryType.REDUCED_SITTING:
            counts = dict(
                Hearing.objects.filter(
                    court_id=court_id, hearing_date=date, status__in=BLOCKING_STATUSES
                )
                .values_list("status")
                .annotate(n=Count("pk"))
            )
            if counts:
                detail = join_words(
                    (
                        f"{counts[status]} {BLOCKING_LABELS[status][counts[status] != 1]}"
                        for status in BLOCKING_STATUSES
                        if counts.get(status)
                    ),
                    "and",
                )
                raise BusinessError(
                    errors.DATE_HAS_HEARINGS,
                    f"{display_date(date)} has {detail}. Move them to another date first, "
                    "with a bulk move that blocks this date.",
                    field="date",
                )
        entry = CourtCalendarEntry(
            court_id=court_id,
            date=date,
            entry_type=entry_type,
            reason=reason,
            capacity_override=capacity_override,
        )
        if actor is not None and getattr(actor, "pk", None):
            entry.created_by = entry.updated_by = actor
            entry._history_user = actor
        entry.save()
    return entry


def delete_entry(*, court_id, entry_id, actor=None):
    """Remove a calendar entry; the day sits again and nothing moves back (#9.2).

    Raises ``CourtCalendarEntry.DoesNotExist`` for an entry of another court.
    """
    with transaction.atomic():
        lock_court(court_id)
        entry = CourtCalendarEntry.objects.get(pk=entry_id, court_id=court_id)
        if entry.date < business_date():
            raise BusinessError(errors.DATE_IN_PAST, PAST_ENTRY_MESSAGE, field="date")
        if actor is not None and getattr(actor, "pk", None):
            entry._history_user = actor
        entry.delete()


def business_date_info(court_id):
    """Return the business date, whether the court sits and its sitting time (#9.3)."""
    court = Organization.objects.only("code").get(pk=court_id)
    today = business_date()
    return {
        "business_date": today,
        "timezone": TIMEZONE_NAME,
        "sitting": is_sitting_day(court_id, today),
        "sitting_time": conf.sitting_time(court.code.lower()),
    }
