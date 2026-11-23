"""Read-only hearing facts for other modules (spec 0023 #11.7).

Return values are frozen dataclasses, so a caller never holds a hearing model
instance and never writes one.
"""

import datetime
from dataclasses import dataclass
from uuid import UUID

from django.db.models import Count
from django.utils import timezone

from . import conf
from .enums import HearingStatus, Side
from .models import Hearing, HearingDateChange
from .services import calendar


@dataclass(frozen=True)
class HearingRef:
    """One hearing as other modules see it."""

    id: UUID
    case_id: UUID
    court_id: UUID
    hearing_date: datetime.date
    purpose_code: str
    purpose_label: str
    status: str
    sequence: int | None
    mode: str
    started_at: datetime.datetime | None = None
    order_id: UUID | None = None


def _ref(hearing):
    return HearingRef(
        id=hearing.pk,
        case_id=hearing.case_id,
        court_id=hearing.court_id,
        hearing_date=hearing.hearing_date,
        purpose_code=hearing.purpose.code,
        purpose_label=hearing.purpose.label,
        status=hearing.status,
        sequence=hearing.sequence,
        mode=hearing.mode,
        started_at=hearing.started_at,
        order_id=hearing.order_id,
    )


def _hearings():
    return Hearing.objects.select_related("purpose")


def get_hearing(hearing_id) -> HearingRef | None:
    """Return the hearing, or None."""
    hearing = _hearings().filter(pk=hearing_id).first()
    return _ref(hearing) if hearing else None


def get_hearings(hearing_ids) -> dict[UUID, HearingRef]:
    """Return ``{hearing_id: HearingRef}`` for the hearings. One query."""
    return {hearing.pk: _ref(hearing) for hearing in _hearings().filter(pk__in=list(hearing_ids))}


def next_hearing(case_id) -> HearingRef | None:
    """Return the case's hearing in progress, else its scheduled one, else None (``OVW-01``)."""
    for status in (HearingStatus.IN_PROGRESS, HearingStatus.SCHEDULED):
        hearing = _hearings().filter(case_id=case_id, status=status).first()
        if hearing:
            return _ref(hearing)
    return None


def has_scheduled_hearing(case_id) -> bool:
    """Whether the case has a scheduled hearing (Advance / Postpone "Available when")."""
    return Hearing.objects.filter(case_id=case_id, status=HearingStatus.SCHEDULED).exists()


def hearings_of_case(case_id) -> list[HearingRef]:
    """Return the case's announced hearings, newest first; provisional and released are left out."""
    return [
        _ref(hearing)
        for hearing in _hearings()
        .filter(case_id=case_id)
        .exclude(status__in=(HearingStatus.PROVISIONAL, HearingStatus.RELEASED))
        .order_by("-hearing_date", "-created_at")
    ]


def adjournment_counts(case_id) -> dict[str, int]:
    """Count the case's adjournments by side (#11.3).

    One per hearing ended with ``adjournment_sought_by``, and one per move by
    whoever sought it; court-side moves count against ``COURT``. Two queries.
    """
    counts = dict.fromkeys(Side.values, 0)
    ended = (
        Hearing.objects.filter(case_id=case_id, status=HearingStatus.COMPLETED)
        .exclude(adjournment_sought_by="")
        .values_list("adjournment_sought_by")
        .annotate(n=Count("pk"))
    )
    moved = (
        HearingDateChange.objects.filter(hearing__case_id=case_id)
        .values_list("sought_by")
        .annotate(n=Count("pk"))
    )
    for side, n in (*ended, *moved):
        counts[side] += n
    return counts


def day_load(court_id, date) -> calendar.DayLoad:
    """Return the court's sitting, capacity, listed and provisional counts for the date (#4)."""
    return calendar.day_load(court_id, date)


def stale_holds(court_id) -> int:
    """Count the court's holds older than ``stale_hold_days`` (#7.4, #11.4)."""
    cutoff = timezone.now() - datetime.timedelta(days=conf.stale_hold_days())
    return Hearing.objects.filter(
        court_id=court_id, status=HearingStatus.PROVISIONAL, created_at__lt=cutoff
    ).count()


def scheduled_hearing(case_id) -> HearingRef | None:
    """Return the case's ``SCHEDULED`` hearing, or None (spec 0039 #6.4, ``ORD-08``)."""
    hearing = _hearings().filter(case_id=case_id, status=HearingStatus.SCHEDULED).first()
    return _ref(hearing) if hearing else None


@dataclass(frozen=True)
class AttendanceLine:
    """One marked line of a hearing's roll, as an order prints it (spec 0039 #5.3, ``ATT-03``)."""

    attendee_type: str
    name: str
    mark: str
    appearance_mode: str


def attendance_lines(hearing_id) -> list[AttendanceLine]:
    """Return the hearing's marked roll lines in roll order, names read from the case."""
    from apps.cases.selectors import get_attendance_roll

    from .models import Hearing, HearingAttendance

    case_id = Hearing.objects.filter(pk=hearing_id).values_list("case_id", flat=True).first()
    if case_id is None:
        return []
    marks = {
        (row.attendee_type, row.participant_id): row
        for row in HearingAttendance.objects.filter(hearing_id=hearing_id)
    }
    lines = []
    for entry in get_attendance_roll(case_id):
        row = marks.get((entry.type, entry.participant_id))
        if row is not None:
            lines.append(AttendanceLine(entry.type, entry.name, row.mark, row.appearance_mode))
    return lines
