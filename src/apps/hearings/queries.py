"""Reads the hearings API serves: the board, counts, the queue, a hearing's detail (spec 0023 #10).

Not the contract other modules use (that is ``selectors``). Each list is
built with one batched call per cases-contract function for the whole page,
never one per row (#10.2).
"""

import datetime

from django.db.models import Count, Q
from django.utils import timezone

from apps.cases import selectors as cases

from . import conf
from .enums import BOARD_STATUSES, HearingStatus, Side
from .models import Hearing, HearingAttendance, HearingDateChange
from .permissions import UNANNOUNCED, allowed_for_roles
from .services import calendar
from .services.common import allowed_actions

LIVE_STATUSES = (
    HearingStatus.SCHEDULED,
    HearingStatus.IN_PROGRESS,
    HearingStatus.PASSED_OVER,
    HearingStatus.PROVISIONAL,
)
ORDERINGS = {
    "status_order": ("status_order", "sequence"),
    "sequence": ("sequence",),
    "hearing_date": ("hearing_date", "status_order", "sequence"),
    "case_number": ("case__case_number",),
    "purpose": ("purpose__sequence", "purpose__code"),
}


def trial_target_cutoff():
    """Cases filed before this moment are beyond the trial target today (#11.2).

    ``days_since_filing > trial_target_days`` means filed before the start, in
    IST, of the day ``trial_target_days`` before today.
    """
    day = calendar.business_date() - datetime.timedelta(days=conf.trial_target_days())
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=calendar.IST)


def adjournment_counts_for(case_ids):
    """``{case_id: {COMPLAINANT, ACCUSED, COURT}}`` for many cases (#11.3). Two queries."""
    counts = {case_id: dict.fromkeys(Side.values, 0) for case_id in case_ids}
    ended = (
        Hearing.objects.filter(case_id__in=case_ids, status=HearingStatus.COMPLETED)
        .exclude(adjournment_sought_by="")
        .values_list("case_id", "adjournment_sought_by")
        .annotate(n=Count("pk"))
    )
    moved = (
        HearingDateChange.objects.filter(hearing__case_id__in=case_ids)
        .values_list("hearing__case_id", "sought_by")
        .annotate(n=Count("pk"))
    )
    for case_id, side, n in (*ended, *moved):
        counts[case_id][side] += n
    return counts


def _case_view(summary, today, target):
    if summary is None:
        return None
    filed = summary.filed_at.astimezone(calendar.IST).date() if summary.filed_at else None
    days = (today - filed).days if filed else None
    return {
        "id": summary.id,
        "display_number": summary.display_number,
        "title": summary.title,
        "stage": summary.stage,
        "days_since_filing": days,
        "beyond_trial_target": days is not None and days > target,
    }


def hearing_views(hearings, roles=None, roles_by_court=None):
    """Return the representation of each hearing (#10.2), as dicts the serializer renders.

    ``roles`` are the caller's roles in the hearings' court (one court), or
    ``roles_by_court`` maps court id to roles; a party has none and gets no
    ``allowed_actions``. One call each to the case summaries and advocates,
    two queries for the adjournments, for the whole list.
    """
    hearings = list(hearings)
    case_ids = list({hearing.case_id for hearing in hearings})
    summaries = cases.get_case_summaries(case_ids)
    advocates = cases.get_case_advocates(case_ids)
    adjournments = adjournment_counts_for(case_ids)
    today = calendar.business_date()
    target = conf.trial_target_days()
    views = []
    for hearing in hearings:
        held = roles if roles_by_court is None else roles_by_court.get(hearing.court_id)
        view = {
            "hearing": hearing,
            "case": _case_view(summaries.get(hearing.case_id), today, target),
            "advocates": advocates.get(hearing.case_id, []),
            "adjournments": adjournments[hearing.case_id],
        }
        if held:
            view["allowed_actions"] = allowed_for_roles(allowed_actions(hearing, today), held)
        views.append(view)
    return views


def hearing_view(hearing, roles):
    """One hearing's representation."""
    return hearing_views([hearing], roles=roles)[0]


# The board (#10.3)


def board(court_id, filters):
    """Return the court's hearings matching the board filters, ordered (#10.3).

    ``filters`` are the validated query parameters. Dates default to the
    business date, statuses to the board's; ``not_reached`` lists every
    abandoned hearing, whatever its date.
    """
    queryset = Hearing.objects.select_related("purpose").filter(court_id=court_id)
    dates, date_from, date_to = (
        filters.get("date"),
        filters.get("date_from"),
        filters.get("date_to"),
    )
    if filters.get("not_reached"):
        queryset = queryset.filter(status=HearingStatus.ABANDONED)
    else:
        queryset = queryset.filter(status__in=filters.get("status") or BOARD_STATUSES)
    if dates:
        queryset = queryset.filter(hearing_date__in=dates)
    if date_from:
        queryset = queryset.filter(hearing_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(hearing_date__lte=date_to)
    if not (dates or date_from or date_to or filters.get("not_reached") or filters.get("case")):
        queryset = queryset.filter(hearing_date=calendar.business_date())
    if filters.get("purpose"):
        queryset = queryset.filter(purpose__code__in=filters["purpose"])
    if filters.get("case"):
        queryset = queryset.filter(case_id=filters["case"])
    if filters.get("search"):
        queryset = queryset.filter(case_id__in=cases.search_case_ids(filters["search"], court_id))
    if filters.get("advocate"):
        queryset = queryset.filter(case_id__in=cases.case_ids_represented_by(filters["advocate"]))
    if filters.get("beyond_trial_target") is not None:
        filed_early = cases.case_ids_filed_before(trial_target_cutoff())
        if filters["beyond_trial_target"]:
            queryset = queryset.filter(case_id__in=filed_early)
        else:
            queryset = queryset.exclude(case_id__in=filed_early)
    if filters.get("has_order"):
        queryset = queryset.filter(order_id__isnull=True)
    if filters.get("changed_since"):
        since = filters["changed_since"]
        moved = HearingDateChange.objects.filter(created_at__gte=since).values("hearing_id")
        queryset = queryset.filter(Q(confirmed_at__gte=since) | Q(pk__in=moved))
    ordering = filters.get("ordering") or "status_order"
    descending = ordering.startswith("-")
    fields = ORDERINGS[ordering.lstrip("-")]
    order_by = [f"-{field}" if descending else field for field in fields]
    return queryset.order_by(*order_by, "pk")


def is_one_day(filters):
    """Whether the board filters ask for a single date: one ``date``, or the default today.

    ``not_reached`` and ``case`` without a date span every date.
    """
    if filters.get("date_from") or filters.get("date_to"):
        return False
    dates = filters.get("date") or []
    if dates:
        return len(dates) == 1
    return not (filters.get("not_reached") or filters.get("case"))


def counts(court_id):
    """Badge counts for the court (#10.4.4); hearing-owned counts only."""
    today = calendar.business_date()
    by_status = dict(
        Hearing.objects.filter(court_id=court_id, hearing_date=today, status__in=BOARD_STATUSES)
        .values_list("status")
        .annotate(n=Count("pk"))
    )
    stale_cutoff = timezone.now() - datetime.timedelta(days=conf.stale_hold_days())
    return {
        "today": sum(by_status.values()),
        "by_status": {status: by_status.get(status, 0) for status in BOARD_STATUSES},
        "not_reached": Hearing.objects.filter(
            court_id=court_id, status=HearingStatus.ABANDONED
        ).count(),
        "scheduling_queue": _queue_case_ids(court_id).count(),
        "stale_holds": Hearing.objects.filter(
            court_id=court_id, status=HearingStatus.PROVISIONAL, created_at__lt=stale_cutoff
        ).count(),
    }


# The scheduling queue (#10.4.8)

NEWLY_REGISTERED = "NEWLY_REGISTERED"
NO_NEXT_DATE = "NO_NEXT_DATE"
HEARING_CANCELLED = "HEARING_CANCELLED"
QUEUE_REASONS = (NEWLY_REGISTERED, NO_NEXT_DATE, HEARING_CANCELLED)


def _queue_case_ids(court_id):
    live = Hearing.objects.filter(status__in=LIVE_STATUSES).values("case_id")
    return cases.cases_awaiting_hearing(court_id).exclude(pk__in=live)


def _event_time(hearing):
    """When the hearing last ended for the case: cancelled, heard or abandoned."""
    return hearing.cancelled_at or hearing.ended_at or hearing.abandoned_at or hearing.updated_at


def scheduling_queue(court_id):
    """Cases of the court that are listable and have no live hearing, longest waiting first.

    Computed, never stored, so it cannot drift. Each item says why the case
    waits and since when: the last hearing's end or cancellation, else the
    registration date.
    """
    case_ids = list(_queue_case_ids(court_id))
    summaries = cases.get_case_summaries(case_ids)
    advocates = cases.get_case_advocates(case_ids)
    # The case's latest event decides why it waits: a hearing heard, abandoned or
    # cancelled most recently, whatever the dates the hearings were listed for.
    last = {}
    announced = Hearing.objects.filter(case_id__in=case_ids).exclude(status__in=UNANNOUNCED)
    for hearing in announced:
        current = last.get(hearing.case_id)
        if current is None or _event_time(hearing) > _event_time(current):
            last[hearing.case_id] = hearing
    items = []
    for case_id in case_ids:
        summary = summaries[case_id]
        hearing = last.get(case_id)
        if hearing is None:
            reason, since = NEWLY_REGISTERED, summary.registered_at
        elif hearing.status == HearingStatus.CANCELLED:
            reason, since = HEARING_CANCELLED, hearing.cancelled_at
        else:
            reason = NO_NEXT_DATE
            since = hearing.ended_at or hearing.abandoned_at or hearing.updated_at
        items.append(
            {
                "case": _case_view(summary, calendar.business_date(), conf.trial_target_days()),
                "advocates": advocates.get(case_id, []),
                "waiting_since": since,
                "reason": reason,
            }
        )
    items.sort(key=lambda item: (item["waiting_since"] is None, item["waiting_since"]))
    return items


# A hearing's detail (#10.2)


def _ref(hearing):
    if hearing is None:
        return None
    return {
        "id": hearing.pk,
        "hearing_date": hearing.hearing_date,
        "purpose": hearing.purpose,
        "status": hearing.status,
    }


def _attendance(hearing):
    roll = cases.get_attendance_roll(hearing.case_id)
    names = {(entry.type, str(entry.participant_id)): entry.name for entry in roll}
    rows = list(HearingAttendance.objects.filter(hearing=hearing))
    marked = {(row.attendee_type, str(row.participant_id)) for row in rows}
    marks = [
        {
            "attendee_type": row.attendee_type,
            "participant_id": row.participant_id,
            "name": names.get((row.attendee_type, str(row.participant_id)), ""),
            "mark": row.mark,
            "appearance_mode": row.appearance_mode,
        }
        for row in rows
    ]
    present = [
        f"{m['name']} ({'video' if m['appearance_mode'] == 'VIDEO' else 'in person'})"
        for m in marks
        if m["mark"] == "PRESENT"
    ]
    absent = [m["name"] for m in marks if m["mark"] == "ABSENT"]
    line = " ".join(
        part
        for part in (
            f"Present: {', '.join(present)}." if present else "",
            f"Absent: {', '.join(absent)}." if absent else "",
        )
        if part
    )
    return {
        "marks": marks,
        "complete": bool(roll) and all((e.type, str(e.participant_id)) in marked for e in roll),
        "locked": hearing.attendance_locked_at is not None,
        "line": line,
    }


def hearing_detail(hearing, roles):
    """The representation plus attendance, date changes and the hearings before and after (#10.2)."""
    view = hearing_view(hearing, roles)
    previous = (
        Hearing.objects.select_related("purpose").filter(pk=hearing.previous_hearing_id).first()
        if hearing.previous_hearing_id
        else None
    )
    following = (
        Hearing.objects.select_related("purpose")
        .filter(previous_hearing=hearing)
        .exclude(status__in=UNANNOUNCED)
        .order_by("-created_at")
        .first()
    )
    view.update(
        attendance=_attendance(hearing),
        date_changes=list(
            HearingDateChange.objects.filter(hearing=hearing)
            .select_related("from_purpose", "to_purpose")
            .order_by("created_at")
        ),
        previous_hearing=_ref(previous),
        next_hearing=_ref(following),
    )
    return view


def case_hearings(case_id, roles):
    """The case's hearings, newest first; a party never sees provisional or released ones."""
    queryset = Hearing.objects.select_related("purpose").filter(case_id=case_id)
    if not roles:
        queryset = queryset.exclude(status__in=UNANNOUNCED)
    return queryset.order_by("-hearing_date", "-created_at")


def case_next_hearing(case_id):
    """The case's hearing in progress, else its scheduled one, else None (``OVW-01``)."""
    for status in (HearingStatus.IN_PROGRESS, HearingStatus.SCHEDULED):
        hearing = (
            Hearing.objects.select_related("purpose").filter(case_id=case_id, status=status).first()
        )
        if hearing:
            return hearing
    return None
