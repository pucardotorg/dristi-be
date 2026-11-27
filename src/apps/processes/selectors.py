"""Reads for the process lists, counts and the case's register (spec 0028 #11.2, #11.3)."""

from collections import Counter
from itertools import groupby
from operator import attrgetter

from django.db.models import Count, Q

from apps.cases.selectors import search_case_ids

from . import conf, steps
from .enums import ProcessStatus, Step
from .models import NonDeliveryReason, Process

ORDERINGS = {
    "status_at": "status_at",
    # The hearing's current date, not the date at issue (#11.2).
    "hearing_date": "hearing_date",
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
    # An envelope is due exactly where receiving one is a step that applies now.
    for flag, where in (
        ("envelope_due", steps.STEPS[Step.RECEIVE_ENVELOPE].where),
        ("fee_paid", Q(fee_paid=True)),
    ):
        if query.get(flag) is not None:
            rows = rows.filter(where if query[flag] else ~where)
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
    """Counts for a screen's tabs and pills, and of the caller's moves.

    ``breakdown`` counts each status, channel and process type together, so a
    screen can count any pill: *To publish* is ``SIGNED`` proclamations by
    hand, *To hand over* the other ``SIGNED`` processes by hand.
    ``by_status_channel`` is ``{status: {channel: n}}``, e.g. *To post* is
    ``SIGNED`` on RPAD and Police (RPAD); ``by_status`` and ``by_channel`` are
    its totals.
    """
    rows = Process.objects.filter(round__court_id=court_id)
    cells = (
        rows.values_list("status", "channel__code", "process_type__code")
        .annotate(n=Count("pk"))
        .order_by("status", "channel__code", "process_type__code")
    )
    breakdown, by_status_channel = [], {}
    by_status, by_channel = Counter(), Counter()
    for status, channel, process_type, n in cells:
        breakdown.append(
            {"status": status, "channel": channel, "process_type": process_type, "count": n}
        )
        of_status = by_status_channel.setdefault(status, {})
        of_status[channel] = of_status.get(channel, 0) + n
        by_status[status] += n
        by_channel[channel] += n
    return {
        "by_status": dict(by_status),
        "by_channel": dict(by_channel),
        "by_status_channel": by_status_channel,
        "breakdown": breakdown,
        "my_moves": rows.filter(steps.my_move_filter(user, court_id)).count(),
    }


def non_delivery_reasons(process_type=None):
    """The state's active reasons; with ``process_type`` (a code), only those for it (``DSP-09``).

    A reason that names no process type is for every type.
    """
    rows = NonDeliveryReason.objects.active().filter(state_code=conf.state_code())
    if process_type:
        rows = rows.filter(
            Q(process_types__isnull=True) | Q(process_types__code=process_type)
        ).distinct()
    return rows.prefetch_related("process_types")


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
