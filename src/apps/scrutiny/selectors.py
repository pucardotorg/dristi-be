"""Read models: the lists, the details, history and the filer's correction view (spec 0024 #7).

Lists are split in two: ``*_list`` returns the filtered, ordered rounds and
the tab counts, for the view to paginate; ``*_rows`` turns one page of rounds
into rows with a fixed number of queries (case columns from one batched
summary call, flag counts from one aggregate).
"""

import datetime
from collections import defaultdict

from django.db.models import Case as Choice
from django.db.models import Count, DateTimeField, Exists, F, OuterRef, Q, Subquery, When
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.cases.models import CaseParticipant, CaseStatus
from apps.core import services as configuration
from apps.organizations.models import Organization

from . import case_selectors, ports
from .checks.service import evaluate_checks
from .enums import CourtRole, FlagStatus, FlagTarget, ResponseKind, RoundDecision, RoundStage
from .models import ScrutinyFlag, ScrutinyRound

TABS = ("registry", "advocate", "closed")
CLAIMED = ("me", "unassigned", "anyone")
CLOSED_TAB_DAYS = 30

STAGE_LABELS = {
    "AWAITING_SCRUTINY": "Awaiting scrutiny",
    "UNDER_SCRUTINY": "Under scrutiny",
    "AWAITING_RESCRUTINY": "Awaiting re-scrutiny",
    "SENT_BACK": "Sent back",
    "FORWARDED": "Forwarded",
    "REGISTERED": "Registered",
}
LIST_STAGES = tuple(STAGE_LABELS)
# ``waiting_days`` ascending is the most recent first.
REGISTRATION_ORDERING = {
    "-waiting_days": ("case__filed_at", "case__filing_number"),
    "waiting_days": ("-case__filed_at", "case__filing_number"),
}
RESPONSE_VERBS = {
    ResponseKind.CORRECTED: "corrected",
    ResponseKind.REUPLOADED: "re-uploaded",
    ResponseKind.EXPLAINED: "answered",
}
# Every status a flag can be in once it has been sent to the filer.
SENT = (FlagStatus.RAISED, FlagStatus.RESPONDED, FlagStatus.CARRIED, FlagStatus.RESOLVED)


# Shared pieces


def _local(moment):
    return timezone.localdate(moment) if moment else None


def _day(moment):
    """``13 Jul``, as the history writes dates."""
    day = _local(moment)
    return f"{day.day} {day:%b}" if day else ""


def _items(count):
    return f"{count} item{'' if count == 1 else 's'}"


def _person(user):
    return {"id": user.pk, "name": user.name} if user else None


def response_view(response):
    return {
        "kind": response.kind,
        "note": response.note,
        "value_after": response.value_after,
        "document_id": response.document_id,
        "responded_at": response.responded_at,
        # An explanation without a change is contested (#3.6).
        "contested": response.kind == ResponseKind.EXPLAINED,
    }


def _last_response(flag):
    responses = list(flag.responses.all())
    return responses[-1] if responses else None


def _chain(flag):
    """Return the earlier copies of a carried item, newest first."""
    history, item = [], flag.carried_from
    while item is not None:
        history.append(
            {
                "flag_id": item.pk,
                "round": item.round.number,
                "stage": item.round.stage,
                "note": item.note,
                "status": item.status,
                "responses": [response_view(response) for response in item.responses.all()],
            }
        )
        item = item.carried_from
    return history


def flag_view(flag):
    return {
        "id": flag.pk,
        "target_type": flag.target_type,
        "target_ref": flag.target_ref,
        "target_label": flag.target_label,
        "section_id": flag.section_id,
        "reason_code": flag.reason_code,
        "note": flag.note,
        "value_at_flag": flag.value_at_flag,
        "status": flag.status,
        "auto_marked_by": flag.auto_marked_by_id,
        "linked_flag": flag.linked_flag_id,
        "carried_from": flag.carried_from_id,
        "resolved_at": flag.resolved_at,
        "responses": [response_view(response) for response in flag.responses.all()],
        "history": _chain(flag),
    }


def _round_flags(round_):
    return list(
        round_.flags.exclude(status=FlagStatus.WITHDRAWN)
        .select_related("carried_from__round")
        .prefetch_related("responses", "carried_from__responses")
        .order_by("created_at")
    )


def _is_carried_open(flag):
    return flag.status == FlagStatus.DRAFT and flag.carried_from_id is not None


def _round_summary(case, round_):
    """``"3 rounds · 1 item open since 7 Jul"``: since the earliest open item was first raised."""
    count = ScrutinyRound.objects.filter(case=case).count()
    text = f"{count} round{'' if count == 1 else 's'}"
    open_items = [flag for flag in _round_flags(round_) if _is_carried_open(flag)]
    if not open_items:
        return text
    raised = []
    for flag in open_items:
        root = flag
        while root.carried_from is not None:
            root = root.carried_from
        raised.append(root.round.decided_at)
    return f"{text} · {_items(len(open_items))} open since {_day(min(filter(None, raised)))}"


def _courtroom(courtroom_id):
    room = Organization.objects.filter(pk=courtroom_id).only("name").first()
    return {"id": room.pk, "name": room.name} if room else None


def _choices(round_):
    return {
        "courtrooms": [
            {"id": room.pk, "name": room.name} for room in ports.courtrooms(round_.establishment_id)
        ],
        "registration_types": [
            {"code": kind.code, "label": kind.label}
            for kind in ports.registration_types(round_.establishment_id)
        ],
    }


def allowed_actions(round_, roles):
    """Return what the caller may do: the round's stage combined with the roles they hold (#7.2)."""
    if not round_.is_open:
        return []
    started = [] if round_.started_by_id else ["start"]
    if round_.stage == RoundStage.SCRUTINY:
        if CourtRole.SCRUTINY_OFFICER not in roles:
            return []
        # Forward is never offered to someone who would forward to themselves (SCR-11).
        decide = "register" if CourtRole.CASE_REGISTERER in roles else "forward"
        return [*started, "flag", "send_back", decide, "edit_title"]
    if CourtRole.CASE_REGISTERER not in roles:
        return []
    return [*started, "register", "send_back", "edit_title"]


# Lists (#7.1, #7.3)


def _latest_rounds():
    latest = (
        ScrutinyRound.objects.filter(case=OuterRef("case")).order_by("-created_at").values("pk")[:1]
    )
    return ScrutinyRound.objects.filter(pk=Subquery(latest))


def _search(rounds, text):
    names = CaseParticipant.objects.active().filter(
        case=OuterRef("case"), name_at_filing__icontains=text
    )
    return rounds.filter(
        Q(case__filing_number__icontains=text)
        | Q(case__case_number__icontains=text)
        | Exists(names)
    )


def _tab_filter(tab, closed_since):
    if tab == "registry":
        return Q(stage=RoundStage.SCRUTINY, decision="")
    if tab == "advocate":
        return Q(decision=RoundDecision.SENT_BACK)
    # Forwarded (now at registration) or registered, recently.
    moved_on = Q(
        stage=RoundStage.SCRUTINY,
        decision__in=(RoundDecision.FORWARDED, RoundDecision.REGISTERED),
    ) | Q(stage=RoundStage.REGISTRATION, decision__in=("", RoundDecision.REGISTERED))
    return moved_on & Q(waiting_from__gte=closed_since)


def scrutiny_list(user, *, tab="registry", claimed="anyone", search="", establishment_id=None):
    """Return ``{"counts", "rounds"}`` for the scrutiny officer's list (#7.1).

    One row per case, from its latest round: *with registry* while its
    scrutiny round is open, *with advocate* once sent back, *closed* once
    forwarded or registered within ``scrutiny.closed_tab_days``. Longest
    waiting first, then filing number.
    """
    rounds = _latest_rounds().annotate(
        # Waiting since the round opened (registry, forwarded) or was decided.
        waiting_from=Choice(
            When(decision="", then=F("created_at")),
            When(
                stage=RoundStage.REGISTRATION,
                decision=RoundDecision.REGISTERED,
                then=F("created_at"),
            ),
            default=F("decided_at"),
            output_field=DateTimeField(),
        )
    )
    if establishment_id:
        rounds = rounds.filter(establishment_id=establishment_id)
    if claimed == "me":
        rounds = rounds.filter(started_by=user)
    elif claimed == "unassigned":
        rounds = rounds.filter(started_by__isnull=True)
    if search and search.strip():
        rounds = _search(rounds, search.strip())
    days = configuration.get_int("scrutiny", "closed_tab_days", CLOSED_TAB_DAYS)
    closed_since = timezone.now() - datetime.timedelta(days=days)
    counts = rounds.aggregate(
        **{name: Count("pk", filter=_tab_filter(name, closed_since)) for name in TABS}
    )
    page = (
        rounds.filter(_tab_filter(tab, closed_since))
        .select_related("case", "started_by")
        .order_by("waiting_from", "case__filing_number")
    )
    return {"counts": counts, "rounds": page}


def _flag_stats(round_ids):
    """Return per round: open carried items, how many were answered or contested, items raised."""
    distinct = {"distinct": True}
    rows = (
        ScrutinyFlag.objects.filter(round_id__in=round_ids)
        .values("round_id")
        .annotate(
            open=Count(
                "pk", filter=Q(status=FlagStatus.DRAFT, carried_from__isnull=False), **distinct
            ),
            answered=Count(
                "pk",
                filter=Q(status=FlagStatus.DRAFT, carried_from__responses__isnull=False),
                **distinct,
            ),
            contested=Count(
                "pk",
                filter=Q(
                    status=FlagStatus.DRAFT, carried_from__responses__kind=ResponseKind.EXPLAINED
                ),
                **distinct,
            ),
            raised=Count(
                "pk",
                filter=Q(
                    status__in=(FlagStatus.RAISED, FlagStatus.RESPONDED),
                    auto_marked_by__isnull=True,
                ),
                **distinct,
            ),
        )
    )
    stats = defaultdict(lambda: {"open": 0, "answered": 0, "contested": 0, "raised": 0})
    for row in rows:
        stats[row.pop("round_id")] = row
    return stats


def _stage_and_reason(round_, summary, stat):
    """Return the list's stage and its reason line (#7.1)."""
    open_line = f"{_items(stat['open'])} open" if stat["open"] else ""
    if round_.decision == RoundDecision.SENT_BACK:
        # A registration send back raises no items, only the registerer's comment.
        if round_.stage == RoundStage.REGISTRATION:
            return "SENT_BACK", "Sent back at registration"
        return "SENT_BACK", f"Sent back with {_items(stat['raised'])}"
    if round_.decision == RoundDecision.REGISTERED:
        return "REGISTERED", summary["case_number"] or ""
    if round_.stage == RoundStage.REGISTRATION or round_.decision:
        return "FORWARDED", open_line
    if round_.started_by_id:
        return "UNDER_SCRUTINY", open_line
    if round_.number == 1:
        return (
            "AWAITING_SCRUTINY",
            round_.get_routing_reason_display() if round_.routing_reason else "",
        )
    if stat["contested"]:
        return "AWAITING_RESCRUTINY", f"{_items(stat['contested'])} contested"
    if stat["open"] and stat["answered"] == stat["open"]:
        return "AWAITING_RESCRUTINY", "All items answered"
    return "AWAITING_RESCRUTINY", open_line


def scrutiny_rows(rounds, today=None):
    """Return the list rows for one page of ``scrutiny_list`` rounds."""
    rounds = list(rounds)
    today = today or timezone.localdate()
    summaries = case_selectors.get_case_summaries({round_.case_id for round_ in rounds})
    stats = _flag_stats([round_.pk for round_ in rounds])
    rows = []
    for round_ in rounds:
        summary = summaries[round_.case_id]
        stage, reason = _stage_and_reason(round_, summary, stats[round_.pk])
        rows.append(
            {
                "case_id": round_.case_id,
                "filing_number": summary["filing_number"],
                "parties": summary["parties"],
                "case_type": summary["case_type"],
                "stage": stage,
                "stage_label": STAGE_LABELS[stage],
                "reason": reason,
                "advocate": summary["advocate"],
                "with": _person(round_.started_by),
                "waiting_days": (today - _local(round_.waiting_from)).days,
                "round": round_.number,
                # Tasks come with the 0011 engine.
                "task_id": None,
            }
        )
    return rows


def registration_list(user, *, search="", ordering="-waiting_days", establishment_id=None):
    """Return the open registration rounds for the Case registerer's list (#7.3)."""
    rounds = ScrutinyRound.objects.filter(stage=RoundStage.REGISTRATION, decision="")
    if establishment_id:
        rounds = rounds.filter(establishment_id=establishment_id)
    if search and search.strip():
        rounds = _search(rounds, search.strip())
    order = REGISTRATION_ORDERING.get(ordering, REGISTRATION_ORDERING["-waiting_days"])
    return rounds.select_related("case").order_by(*order)


def registration_rows(rounds, today=None):
    """Return the list rows for one page of ``registration_list`` rounds."""
    rounds = list(rounds)
    today = today or timezone.localdate()
    summaries = case_selectors.get_case_summaries({round_.case_id for round_ in rounds})
    stats = _flag_stats([round_.pk for round_ in rounds])
    rooms = Organization.objects.in_bulk({round_.courtroom_id for round_ in rounds} - {None})
    rows = []
    for round_ in rounds:
        summary = summaries[round_.case_id]
        room = rooms.get(round_.courtroom_id)
        submitted = summary["submitted_at"]
        rows.append(
            {
                "case_id": round_.case_id,
                "case_name": summary["parties"],
                "filing_number": summary["filing_number"],
                "advocates": summary["advocates"],
                "days_since_submitted": (today - submitted).days if submitted else None,
                "days_since_cleared": (today - _local(round_.created_at)).days,
                "open_items": stats[round_.pk]["open"],
                "courtroom": {"id": room.pk, "name": room.name} if room else None,
                "registration_type": round_.registration_type,
                "round": round_.number,
            }
        )
    return rows


# Details (#7.2, #7.4)


def scrutiny_detail(case, round_, user, today=None):
    """Return one filing as the Scrutiny officer sees it, for ``round_`` (#7.2)."""
    today = today or timezone.localdate()
    summary = case_selectors.get_case_summary(case)
    catalogue = ports.fields(case, today)
    flags = _round_flags(round_)
    live = {(flag.target_type, flag.target_ref): flag.pk for flag in flags}
    sections = case_selectors.get_filing_view(case, catalogue)
    for section in sections:
        for group in section["groups"]:
            for field in group["fields"]:
                field["flag_id"] = live.get((FlagTarget.FIELD, field["ref"]))
    bundle = case_selectors.get_bundle(case)
    for item in bundle:
        item["flag_id"] = live.get((FlagTarget.DOCUMENT, str(item["document_id"])))
    previous = (
        ScrutinyRound.objects.filter(case=case, created_at__lt=round_.created_at)
        .order_by("-created_at")
        .first()
    )
    establishment = Organization.objects.filter(pk=round_.establishment_id).first()
    detail = {
        "case": {
            "id": case.pk,
            "filing_number": summary["filing_number"],
            "parties": summary["parties"],
            "submitted_at": summary["submitted_at"],
            "advocate": summary["advocate"],
        },
        "round": {
            "id": round_.pk,
            "stage": round_.stage,
            "number": round_.number,
            "started_by": _person(round_.started_by),
            "summary": _round_summary(case, round_),
        },
        "sections": sections,
        "bundle": bundle,
        "checklist": case_selectors.checklist(case),
        "alerts": evaluate_checks(establishment, case_selectors.check_facts(case, today)),
        **_choices(round_),
        "flags": {
            "draft": [
                flag_view(flag)
                for flag in flags
                if flag.status == FlagStatus.DRAFT and flag.carried_from_id is None
            ],
            "carried": [flag_view(flag) for flag in flags if flag.carried_from_id is not None],
            "raised_last_round": [
                flag_view(flag)
                for flag in (_round_flags(previous) if previous else [])
                if flag.status in SENT
            ],
        },
        "allowed_actions": allowed_actions(round_, ports.roles_held(user, round_.establishment_id)),
        "workflow_version": ports.workflow_version(case),
    }
    if ports.oath_required(case):
        detail["oaths"] = ports.oaths(case)
    return detail


def registration_detail(case, round_, user, today=None):
    """Return a forwarded case as the Case registerer sees it (#7.4)."""
    today = today or timezone.localdate()
    rounds = list(
        ScrutinyRound.objects.filter(case=case)
        .select_related("decided_by", "started_by")
        .order_by("created_at")
    )
    scrutiny_rounds = [item for item in rounds if item.stage == RoundStage.SCRUTINY]
    forwarded = next(
        (
            item
            for item in reversed(scrutiny_rounds)
            if item.decision == RoundDecision.FORWARDED and item.created_at < round_.created_at
        ),
        None,
    )
    if round_.stage != RoundStage.REGISTRATION or forwarded is None:
        raise NotFound("No registration for this case.")
    entered, cleared = _local(scrutiny_rounds[0].created_at), _local(forwarded.decided_at)
    flags = _round_flags(round_)
    return {
        "case": {"id": case.pk, **_case_block(case)},
        "summary": case_selectors.get_registration_summary(case),
        "scrutiny": {
            "cleared_by": _person(forwarded.decided_by),
            "round_count": len(scrutiny_rounds),
            "days_taken": (cleared - entered).days,
            "rounds": [
                _round_brief(item) for item in rounds if item.created_at < round_.created_at
            ],
        },
        "timeline": case_selectors.get_registration_timeline(case, entered, cleared, today),
        "courtroom": _courtroom(round_.courtroom_id),
        "registration_type": round_.registration_type,
        "registration_types": _choices(round_)["registration_types"],
        "open_items": [flag_view(flag) for flag in flags if _is_carried_open(flag)],
        "allowed_actions": allowed_actions(round_, ports.roles_held(user, round_.establishment_id)),
        "workflow_version": ports.workflow_version(case),
    }


def _case_block(case):
    summary = case_selectors.get_case_summary(case)
    return {
        "filing_number": summary["filing_number"],
        "parties": summary["parties"],
        "submitted_at": summary["submitted_at"],
        "advocates": summary["advocates"],
    }


def _round_brief(round_):
    return {
        "id": round_.pk,
        "stage": round_.stage,
        "number": round_.number,
        "started_by": _person(round_.started_by),
        "decision": round_.decision,
        "decided_by": _person(round_.decided_by),
        "decided_at": round_.decided_at,
        "item_count": round_.flags.filter(status__in=SENT, auto_marked_by__isnull=True).count()
        if round_.decision == RoundDecision.SENT_BACK
        else 0,
        "open_items_at_decision": round_.open_items_at_decision,
    }


# History (#7.5)


def _item_state(flag):
    """``corrected 13 Jul``, ``re-uploaded 30 Jul, still open``, ``resolved 3 Aug``."""
    latest = flag
    while (following := latest.carried_to.first()) is not None:
        latest = following
    if latest.status == FlagStatus.RESOLVED:
        return f"resolved {_day(latest.resolved_at)}"
    response = _last_response(flag)
    state = (
        f"{RESPONSE_VERBS[response.kind]} {_day(response.responded_at)}"
        if response
        else "not answered"
    )
    reviewed = latest is not flag and latest.round.started_at is not None
    return f"{state}, still open" if reviewed else state


def _sent_items(round_):
    return [
        flag
        for flag in _round_flags(round_)
        if flag.status in SENT and flag.auto_marked_by_id is None
    ]


def history(case, for_filer=False):
    """Return the round timeline and its header summary (#7.5).

    The filing side sees the same timeline without the court staff's names.
    Draft flags never appear: only items that were sent back are listed.
    """
    rounds = list(
        ScrutinyRound.objects.filter(case=case)
        .select_related("started_by", "decided_by")
        .order_by("created_at")
    )
    entries = []
    if case.filed_at:
        entries.append(_entry("FILED", case.filed_at, f"Filed · {case.created_by.name}"))
    previous = None
    for round_ in rounds:
        entries += _round_entries(case, round_, previous, for_filer)
        previous = round_
    return {
        "summary": _round_summary(case, rounds[-1]) if rounds else "",
        "entries": entries,
    }


def _round_entries(case, round_, previous, for_filer):
    entries = []
    scrutiny = round_.stage == RoundStage.SCRUTINY
    if scrutiny and previous is not None and previous.decision == RoundDecision.SENT_BACK:
        items = _sent_items(previous) if previous.stage == RoundStage.SCRUTINY else []
        answered = sum(1 for flag in items if _last_response(flag))
        contested = sum(
            1
            for flag in items
            if (response := _last_response(flag)) and response.kind == ResponseKind.EXPLAINED
        )
        resubmitted = "Resubmitted"
        if items:
            resubmitted += f" · {answered} of {_items(len(items))} answered"
        entries.append(_entry("RESUBMITTED", round_.created_at, resubmitted, round_))
        entries.append(
            _entry(
                "RETURNED",
                round_.created_at,
                f"Returned to scrutiny · {_items(contested)} contested",
                round_,
            )
        )
    elif scrutiny and previous is None:
        routed = "Routed to scrutiny"
        if round_.routing_reason:
            routed += f" · {round_.get_routing_reason_display()}"
        entries.append(_entry("ROUTED", round_.created_at, routed, round_))
    if round_.started_at:
        started = f"{'Scrutiny' if scrutiny else 'Registration'} started"
        if not for_filer:
            started += f" · {round_.started_by.name}"
        entries.append(_entry("STARTED", round_.started_at, started, round_))
    if round_.decision == RoundDecision.SENT_BACK and scrutiny:
        items = _sent_items(round_)
        entry = _entry(
            "SENT_BACK",
            round_.decided_at,
            f"Sent back with {_items(len(items))} · round {round_.number}",
            round_,
        )
        entry["items"] = [
            {
                "flag_id": flag.pk,
                "label": flag.target_label,
                "what": flag.note or flag.value_at_flag,
                "state": _item_state(flag),
            }
            for flag in items
        ]
        entries.append(entry)
    elif round_.decision == RoundDecision.SENT_BACK:
        entry = _entry(
            "SENT_BACK_AT_REGISTRATION", round_.decided_at, "Sent back at registration", round_
        )
        entry["comment"] = round_.comment
        entries.append(entry)
    elif round_.decision == RoundDecision.FORWARDED:
        room = _courtroom(round_.courtroom_id)
        text = f"Forwarded · {room['name']}" if room else "Forwarded"
        entries.append(_entry("FORWARDED", round_.decided_at, text, round_))
    elif round_.decision == RoundDecision.REGISTERED:
        text = f"Registered · {case.case_number}" if case.case_number else "Registered"
        entries.append(_entry("REGISTERED", round_.decided_at, text, round_))
    return entries


def _entry(kind, at, text, round_=None):
    return {
        "kind": kind,
        "at": at,
        "text": text,
        "round": round_.number if round_ else None,
        "stage": round_.stage if round_ else None,
    }


# Filer correction view (#7.6)


def corrections(case):
    """Return the items of the latest send back, as the filing side corrects them.

    Grouped as the screen groups them: *Flags — advocate fixes* and *Document
    issues — advocate re-uploads*; for a registration send back, the Case
    registerer's comment instead. ``open`` says whether the case is still in
    correction, and per item whether its target may be changed.
    """
    round_ = ScrutinyRound.objects.filter(case=case).order_by("-created_at").first()
    empty = {
        "open": False,
        "mode": None,
        "round": None,
        "comment": "",
        "flags": [],
        "document_issues": [],
    }
    if round_ is None or round_.decision != RoundDecision.SENT_BACK:
        return empty
    in_correction = case.status == CaseStatus.PENDING_CORRECTION
    view = {**empty, "open": in_correction, "round": round_.number}
    if round_.stage == RoundStage.REGISTRATION:
        return {**view, "mode": "ALL", "comment": round_.comment}
    scope = (ports.correction_scope(case) or {}) if in_correction else {}
    scoped = {
        FlagTarget.FIELD: set(scope.get("fields", [])),
        FlagTarget.SECTION: set(scope.get("sections", [])),
        FlagTarget.DOCUMENT: set(scope.get("documents", [])),
        FlagTarget.OATH: set(scope.get("oaths", [])),
    }
    view["mode"] = "MARKED"
    for flag in _round_flags(round_):
        if flag.status not in SENT:
            continue
        response = _last_response(flag)
        item = {
            "id": flag.pk,
            "target_type": flag.target_type,
            "target_ref": flag.target_ref,
            "target_label": flag.target_label,
            "section_id": flag.section_id,
            "reason_code": flag.reason_code,
            "note": flag.note,
            "status": flag.status,
            "auto_marked_by": flag.auto_marked_by_id,
            "response": response_view(response) if response else None,
            "open": flag.target_ref in scoped[flag.target_type],
        }
        group = "document_issues" if flag.target_type == FlagTarget.DOCUMENT else "flags"
        view[group].append(item)
    return view
