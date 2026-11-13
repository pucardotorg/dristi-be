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
    )


def _hearings():
    return Hearing.objects.select_related("purpose")


def get_hearing(hearing_id) -> HearingRef | None:
    """Return the hearing, or None."""
    hearing = _hearings().filter(pk=hearing_id).first()
    return _ref(hearing) if hearing else None


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
