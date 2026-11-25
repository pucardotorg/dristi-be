"""Reads for the process lists, counts and the case's register (spec 0028 #11.2, #11.3)."""

from itertools import groupby
from operator import attrgetter

from django.db.models import Count, Q

from apps.cases.selectors import search_case_ids

from . import steps
from .enums import ProcessStatus
from .models import Process

ORDERINGS = {
    "status_at": "status_at",
    "hearing_date": "round__hearing_date",
    "expires_at": "expires_at",
    "created_at": "created_at",
}


def processes():
    """Processes with everything a response reads, in one query."""
    return Process.objects.select_related(
        "round", "process_type", "channel", "police_station", "reason"
    )


def court_processes(user, query):
    """One courtroom's processes, filtered and ordered as ``query`` asks (#11.2)."""
    court_id = query["court"]
    rows = processes().filter(round__court_id=court_id)
    filters = {
        "status__in": query.get("status"),
        "process_type__code__in": query.get("process_type"),
        "channel__code__in": query.get("channel"),
        "reason__code__in": query.get("reason"),
        "case_id": query.get("case"),
        "round_id": query.get("round"),
        "hearing_id": query.get("hearing"),
    }
    rows = rows.filter(**{lookup: value for lookup, value in filters.items() if value})
    if query.get("reason"):
        rows = rows.filter(status=ProcessStatus.NOT_DELIVERED)
    if query.get("my_move"):
        rows = rows.filter(steps.my_move_filter(user, court_id))
    if text := query.get("search"):
        rows = rows.filter(
            Q(case_id__in=search_case_ids(text, court_id)) | Q(recipient_name__icontains=text)
        )
    ordering = query.get("ordering") or "status_at"
    field = ORDERINGS[ordering.lstrip("-")]
    return rows.order_by(f"-{field}" if ordering.startswith("-") else field, "created_at")


def counts(user, court_id):
    """Counts per status and channel, and of the caller's moves, for a screen's tabs."""
    rows = Process.objects.filter(round__court_id=court_id)
    return {
        "by_status": dict(rows.values_list("status").annotate(n=Count("pk")).order_by()),
        "by_channel": dict(rows.values_list("channel__code").annotate(n=Count("pk")).order_by()),
        "my_moves": rows.filter(steps.my_move_filter(user, court_id)).count(),
    }


def _runs(rows, *fields):
    """Split ``rows`` into runs of equal ``fields``; ``rows`` are ordered by them."""
    return [list(run) for _, run in groupby(rows, key=attrgetter(*fields))]


def case_register(case_id):
    """The case's processes by person, then round, newest first, one group per type (``SVC-``).

    Returns ``[{"recipient": Process, "groups": [{"first": Process, "processes": [...]}]}]``:
    each group is one round's processes of one type, which share ``first``'s
    round, type and hearing.
    """
    rows = (
        processes()
        .filter(case_id=case_id)
        .order_by(
            "recipient_id", "-round__created_at", "round_id", "process_type__code", "created_at"
        )
    )
    return [
        {
            "recipient": of_person[0],
            "groups": [
                {"first": group[0], "processes": group}
                for group in _runs(of_person, "round_id", "process_type_id")
            ],
        }
        for of_person in _runs(rows, "recipient_id")
    ]
