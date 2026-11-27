"""Read models (spec 0033 #14).

Lists are built from columns and batched case summaries, never per-row
queries; the detail reads the transition log with one prefetch. What a
submitted application shows is the same for everyone who can see it
(``APP-07``, ``ALC-23``); the court view adds what the bench needs to act.
"""

import datetime
from collections import Counter

from django.db.models import Count, Exists, OuterRef, Prefetch, Q, Subquery
from rest_framework.exceptions import NotFound

from apps.cases.selectors import get_case_advocates, get_case_summaries
from apps.hearings import selectors as hearings
from apps.hearings.services.calendar import IST

from . import access, conf, ports
from .enums import (
    DECIDED_STATUSES,
    OPEN_STATUSES,
    ORDER_ACTIONS,
    SUBMITTED_STATUSES,
    Action,
    ApplicationStatus,
    ObjectionStatus,
)
from .models import Application, ApplicationTransition
from .services import actions, rendering
from .services.calendar import today

S = ApplicationStatus

# The type-cut queues of the court (#14.5).
TYPE_QUEUES = {
    "rescheduling": ("ADVANCE_HEARING", "POSTPONE_HEARING"),
    "delay_condonation": ("DELAY_CONDONATION",),
}
COURT_VIEWS = ("all", "onboard", "decide", "signing", "upcoming", "closed", "archive")
CLOSED_STATUSES = (*DECIDED_STATUSES, S.EXPIRED)
CLOSING_ACTIONS = (Action.ACCEPT, Action.REJECT, Action.DISMISS, Action.EXPIRE)


def base_queryset():
    return Application.objects.select_related(
        "application_type",
        "case",
        "case__court",
        "raised_by__advocate_profile",
        "created_by__advocate_profile",
    )


def with_transitions(queryset):
    return queryset.prefetch_related(
        Prefetch(
            "transitions",
            queryset=ApplicationTransition.objects.select_related("actor").order_by("created_at"),
        )
    )


# Names --------------------------------------------------------------------------------


def _litigant_names(applications):
    ids = {a.raised_on_behalf_of for a in applications if a.raised_on_behalf_of}
    if not ids:
        return {}
    from apps.cases.models import CaseParticipant

    return {
        pk: name or entity
        for pk, name, entity in CaseParticipant.objects.filter(pk__in=ids).values_list(
            "pk", "name_at_filing", "entity_name_at_filing"
        )
    }


def _user_name(user):
    if user is None:
        return None
    profile = getattr(user, "advocate_profile", None)
    if profile is not None:
        return f"Adv. {profile.name or user.name}"
    return user.name


# Objection status (#14.4) -------------------------------------------------------------


def objection_status(application, objection=None, *, day=None):
    day = day or today()
    if objection is not None and objection.status == S.SUBMITTED:
        return ObjectionStatus.FILED
    if not application.objections_invited or application.respond_by is None:
        return ObjectionStatus.NOT_CALLED_FOR
    if application.respond_by >= day:
        return ObjectionStatus.DUE
    return ObjectionStatus.NONE_RECEIVED


def _submitted_objection(application):
    try:
        return application.objection
    except Application.DoesNotExist:
        return None


# Lists (#14.1) ------------------------------------------------------------------------


def case_list(case_id, user, *, filters):
    """``GET /cases/{case_id}/applications/`` rows the caller may see (#14.1)."""
    queryset = access.visible_on_case(case_id, user, base_queryset()).annotate(
        has_objection_flag=_submitted_objection_exists(),
        # Any objection, a draft included: it bars a second one (ALC-24).
        any_objection_flag=Exists(Application.objects.filter(objection_to=OuterRef("pk"))),
    )
    queryset = _filter(queryset, filters)
    if filters.get("pending"):
        queryset = queryset.filter(status__in=OPEN_STATUSES)
    ordering = filters.get("ordering") or "-created_at"
    return queryset.order_by(ordering, "-pk")


def _filter(queryset, filters):
    if filters.get("type"):
        queryset = queryset.filter(application_type__code=filters["type"])
    if filters.get("status"):
        queryset = queryset.filter(status=filters["status"])
    if filters.get("filed_by"):
        queryset = queryset.filter(
            Q(raised_by_id=filters["filed_by"])
            | Q(raised_by__isnull=True, created_by_id=filters["filed_by"])
        )
    if filters.get("search"):
        text = filters["search"].strip()
        queryset = queryset.filter(
            Q(application_number__icontains=text)
            | Q(earlier_application_number__icontains=text)
            | Q(application_type__label__icontains=text)
        )
    return queryset


def list_rows(applications, user, case_access_by_case=None):
    """Serialisable list rows (#14.1), with ``actions``, ``waiting_on`` and ``drafted_by``."""
    applications = list(applications)
    names = _litigant_names(applications)
    accesses = case_access_by_case or {}
    rows = []
    for app in applications:
        access_ = accesses.get(app.case_id)
        if access_ is None:
            access_ = ports.case_access(app.case_id, user)
            accesses[app.case_id] = access_
        rows.append(_row(app, user, access_, names))
    return rows


def _row(app, user, case_access, names):
    raised_by = app.raised_by
    in_circle = access.in_drafting_circle(app, user, case_access)
    actions_ = caller_actions(app, user, case_access, in_circle=in_circle)
    waiting_on = None
    if app.status == S.PENDING_SIGNATURE and in_circle and user.pk != app.raised_by_id:
        waiting_on = _user_name(raised_by)
    filer = raised_by or app.created_by
    return {
        "id": app.pk,
        "type": {"code": app.application_type.code, "label": app.application_type.label},
        "application_number": app.application_number,
        "earlier_application_number": app.earlier_application_number,
        "status": app.status,
        "status_label": app.get_status_display(),
        "side": app.side,
        "filed_by": _user_name(filer),
        "filed_by_id": filer.pk if filer else None,
        "drafted_by": _user_name(app.created_by)
        if app.created_by_id and app.created_by_id != app.raised_by_id
        else None,
        "litigant": names.get(app.raised_on_behalf_of),
        "created_at": app.created_at,
        "submitted_at": app.submitted_at,
        "review_due_date": app.review_due_date if app.status == S.PENDING_REVIEW else None,
        "decision_date": app.decision_date,
        "respond_by": app.respond_by,
        "has_objection": bool(getattr(app, "has_objection_flag", False)),
        "deciding_order": {"id": app.deciding_order_id, "number": None}
        if app.deciding_order_id
        else None,
        "outcome": app.outcome or None,
        "waiting_on": waiting_on,
        "actions": actions_,
    }


def caller_actions(app, user, case_access, *, in_circle=None):
    """What the caller can do now (#14.1 ``actions``)."""
    in_circle = (
        access.in_drafting_circle(app, user, case_access) if in_circle is None else in_circle
    )
    found = []
    if app.status == S.DRAFT and in_circle:
        found += ["continue", "discard"]
    if app.status == S.PENDING_SIGNATURE:
        if access.is_signer(app, user, case_access):
            found.append("sign")
        if in_circle:
            found += ["back_to_draft", "discard"]
    if app.status == S.PENDING_PAYMENT:
        if access.on_side(app, user, case_access):
            found.append("pay")
        if in_circle:
            found.append("discard")
    if (
        app.status in OPEN_STATUSES
        and not app.is_objection
        and case_access.is_drafter
        and case_access.side != app.side
        and not _has_any_objection(app)
    ):
        found.append("file_objection")
    return found


def _has_any_objection(app):
    """The annotated flag when listed; one query on a single application."""
    flag = getattr(app, "any_objection_flag", None)
    if flag is not None:
        return flag
    return Application.objects.filter(objection_to=app).exists()


def filers(case_id, user):
    """People who raised a visible application on the case (#14.1 ``filed_by`` options)."""
    seen = {}
    for app in access.visible_on_case(case_id, user, base_queryset()):
        filer = app.raised_by or app.created_by
        if filer is not None and filer.pk not in seen:
            seen[filer.pk] = {"user_id": filer.pk, "name": _user_name(filer), "side": app.side}
    return list(seen.values())


# Needs attention (#14.2) --------------------------------------------------------------


def needs_attention(case_id, user):
    """What still needs a step from the caller, grouped by step and filer (#14.2)."""
    from apps.payments.models import Demand

    case_access = ports.case_access(case_id, user)
    visible = list(access.visible_on_case(case_id, user, base_queryset()).order_by("created_at"))
    groups = {}

    def add(step, label, app, **extra):
        filer = app.raised_by or app.created_by
        key = (step, filer.pk if filer else None)
        group = groups.setdefault(
            key,
            {
                "step": step,
                "action_label": label,
                "filed_by": _user_name(filer),
                "application_ids": [],
                **extra,
            },
        )
        group["application_ids"].append(app.pk)
        return group

    demands = {
        d.pk: d for d in Demand.objects.filter(pk__in=[a.demand_id for a in visible if a.demand_id])
    }
    for app in visible:
        if app.status == S.DRAFT and access.in_drafting_circle(app, user, case_access):
            add("CONTINUE_DRAFT", "Continue draft", app)
        elif app.status == S.PENDING_SIGNATURE and access.is_signer(app, user, case_access):
            # Aadhaar e-sign signs one at a time; DSC / batch signing are not built (APP-10).
            add("ADD_SIGNATURE", "Add signature", app, bulk_signing_available=False)
        elif app.status == S.PENDING_PAYMENT and access.on_side(app, user, case_access):
            group = add(
                "COMPLETE_PAYMENT", "Complete payment", app, demand_ids=[], lines=[], total="0.00"
            )
            demand = demands.get(app.demand_id)
            if demand is not None:
                group["demand_ids"].append(demand.pk)
                group["lines"].append({"application_id": app.pk, "amount": str(demand.due_amount)})
                group["total"] = str(sum(demands[d].due_amount for d in group["demand_ids"]))
    if case_access.is_drafter:
        for app in visible:
            if (
                app.status == S.PENDING_DECISION
                and app.side != case_access.side
                and objection_status(app, _submitted_objection(app)) == ObjectionStatus.DUE
            ):
                groups.setdefault(
                    ("FILE_OBJECTION", app.pk),
                    {
                        "step": "FILE_OBJECTION",
                        "action_label": "File objection",
                        "application_ids": [app.pk],
                        "type": app.application_type.label,
                        "application_number": app.application_number,
                        "respond_by": app.respond_by,
                        "decision_date": app.decision_date,
                    },
                )
    return list(groups.values())


# Detail (#14.3, #14.4) ----------------------------------------------------------------


def _history_text(row):
    if row.summary:
        return row.summary
    actor = _user_name(row.actor)
    action = Action(row.action)
    if action == Action.SIGN and actor:
        return f"Signed by {actor}"
    if action == Action.CREATE:
        return "Draft started"
    return action.label


def _document_names(documents):
    """Number repeated names in order ("Proof of solvency 1", "… 2") (#14.3)."""
    counts = Counter(d.name for d in documents)
    seen = Counter()
    named = []
    for document in documents:
        name = document.name
        if counts[name] > 1:
            seen[name] += 1
            name = f"{name} {seen[name]}"
        named.append((document, name))
    return named


def detail(app, user):
    """``GET /applications/{id}/`` for anyone who can see it (#14.3), plus the court view (#14.4)."""
    app = with_transitions(base_queryset()).filter(pk=app.pk).first()
    case_access = ports.case_access(app.case_id, user) if app is not None else None
    if app is None or not access.can_see(app, user, case_access):
        raise NotFound("Application not found.")
    transitions = list(app.transitions.all())
    in_circle = access.in_drafting_circle(app, user, case_access)
    objection = _submitted_objection(app)
    case_summary = get_case_summaries([app.case_id]).get(app.case_id)
    litigant = ports.participant(app.case_id, app.raised_on_behalf_of)
    hearing = hearings.get_hearing(app.hearing_id) if app.hearing_id else None
    sign_row = next((t for t in reversed(transitions) if t.action == Action.SIGN), None)
    orders = _orders(app, transitions)
    workflow_row = next(
        (t for t in reversed(transitions) if t.action == Action.WORKFLOW_DONE), None
    )
    deferrals = sum(1 for t in transitions if t.action == Action.DEFER_REVIEW)
    # Filing steps to the drafting circle; from submission on, the same timeline to everyone.
    history = [
        {
            "at": t.created_at,
            "action": t.action,
            "actor": {"name": _user_name(t.actor)} if t.actor_id else None,
            "text": _history_text(t),
        }
        for t in transitions
        if t.action != Action.EDIT and (in_circle or t.action not in FILING_ACTIONS)
    ]
    documents = list(app.documents.all())
    named = _document_names(documents)
    signed_doc = (
        [
            {
                "id": None,
                "is_supporting": False,
                "field_path": "",
                "name": f"{app.application_type.label} application",
                "file_id": app.signed_file_id,
            }
        ]
        if app.signed_file_id
        else []
    )
    fee = _fee(app)
    data = {
        "id": app.pk,
        "case": {
            "id": app.case_id,
            "case_number": case_summary.display_number if case_summary else "",
            "title": case_summary.title if case_summary else "",
        },
        "type": {
            "code": app.application_type.code,
            "label": app.application_type.label,
            "template_code": rendering.template_key(app),
        },
        "status": app.status,
        "status_label": app.get_status_display(),
        "side": app.side,
        "application_number": app.application_number,
        "earlier_application_number": app.earlier_application_number,
        "raised_by": {"id": app.raised_by_id, "name": _user_name(app.raised_by)}
        if app.raised_by_id
        else None,
        "litigant": {
            "participant_id": litigant.pk,
            "name": litigant.name_at_filing or litigant.entity_name_at_filing,
        }
        if litigant
        else None,
        "details": app.details,
        "data": app.data,
        "hearing": {
            "id": hearing.id,
            "hearing_date": hearing.hearing_date,
            "purpose_label": hearing.purpose_label,
        }
        if hearing
        else None,
        "documents": signed_doc
        + [
            {
                "id": d.pk,
                "is_supporting": d.is_supporting,
                "field_path": d.field_path,
                "name": name,
                "file_id": d.file_id,
            }
            for d, name in named
        ],
        "signed_file_id": app.signed_file_id or None,
        "signed_at": sign_row.created_at if sign_row else None,
        "signing_methods": list(conf.signing_methods()),
        "fee": str(fee),
        "demand_id": app.demand_id,
        "additional_attributes": app.additional_attributes,
        "created_at": app.created_at,
        "submitted_at": app.submitted_at,
        "filed_on": app.submitted_at,
        "onboarded_at": app.onboarded_at,
        "review_due_date": app.review_due_date,
        "decision_date": app.decision_date,
        "objections_invited": app.objections_invited,
        "respond_by": app.respond_by,
        "outcome": app.outcome or None,
        "objection_status": objection_status(app, objection) if not app.is_objection else None,
        "objection": _linked(objection) if objection and objection.status == S.SUBMITTED else None,
        "objection_to": _linked(app.objection_to) if app.objection_to_id else None,
        "filed_after_deadline": bool(
            app.is_objection
            and app.submitted_at
            and app.objection_to.respond_by
            and app.submitted_at.astimezone(IST).date() > app.objection_to.respond_by
        ),
        "deciding_order": next(
            (
                {"id": o["id"], "number": None, "title": o["title"], "signed_at": o["signed_at"]}
                for o in orders
                if o["deciding"]
            ),
            None,
        ),
        "orders": orders,
        "previous_order": orders[-1] if orders else None,
        "workflow_status": app.workflow_status,
        "workflow_summary": workflow_row.summary or None if workflow_row else None,
        "review_deferred": deferrals > 0,
        "review_deferral_count": deferrals,
        "history": history,
        "drafted_by": _user_name(app.created_by)
        if app.created_by_id and app.created_by_id != app.raised_by_id
        else None,
        "waiting_on": _user_name(app.raised_by)
        if app.status == S.PENDING_SIGNATURE and in_circle and user.pk != app.raised_by_id
        else None,
        "step": _step(app, user, case_access, in_circle),
        "objection_invite": _objection_invite(app, case_access),
        "allowed_actions": caller_actions(app, user, case_access, in_circle=in_circle),
        "version": app.version,
    }
    if access.is_court_reader(app, user):
        data.update(court_view(app, user, objection))
    return data


DECIDING_ACTIONS = (Action.ACCEPT, Action.REJECT, Action.DISMISS)


def _orders(app, transitions):
    """The *Orders* attribute (#14.3): each order once, oldest first.

    An order that onboards and decides wrote two transitions (#8.3); it is one
    order, titled by its last act (the decision) and summarised by both.
    """
    by_order = {}
    for t in transitions:
        if not t.order_id or t.action not in ORDER_ACTIONS:
            continue
        entry = by_order.setdefault(
            t.order_id,
            {"id": t.order_id, "number": None, "signed_at": t.created_at, "summaries": []},
        )
        entry["title"] = Action(t.action).label
        entry["deciding"] = t.order_id == app.deciding_order_id and t.action in DECIDING_ACTIONS
        if t.summary and t.summary not in entry["summaries"]:
            entry["summaries"].append(t.summary)
    orders = []
    for entry in by_order.values():
        summaries = entry.pop("summaries")
        entry["summary"] = "; ".join(summaries)
        orders.append(entry)
    return orders


# Filing steps are shown to the drafting circle only (#14.3 ``history``).
FILING_ACTIONS = (Action.CREATE, Action.EDIT, Action.PROCEED_TO_SIGN, Action.BACK_TO_DRAFT)


def _fee(app):
    from decimal import Decimal

    from apps.payments.models import Demand

    if not app.demand_id:
        return Decimal("0.00")
    return Demand.objects.filter(pk=app.demand_id).values_list(
        "total_amount", flat=True
    ).first() or Decimal("0.00")


def _linked(app):
    return {
        "id": app.pk,
        "type": app.application_type.code,
        "label": app.application_number,
        "status": app.status,
        "submitted_at": app.submitted_at,
        "details": app.details,
        "documents": [
            {"id": d.pk, "name": d.name, "file_id": d.file_id} for d in app.documents.all()
        ],
    }


def _step(app, user, case_access, in_circle):
    if app.status == S.DRAFT and in_circle:
        return "continue"
    if app.status == S.PENDING_SIGNATURE and access.is_signer(app, user, case_access):
        return "sign"
    if app.status == S.PENDING_PAYMENT and access.on_side(app, user, case_access):
        return "pay"
    return None


def _objection_invite(app, case_access):
    """On the other side's application while that side may object and has not started (#14.3)."""
    if (
        app.is_objection
        or app.status not in OPEN_STATUSES
        or not case_access.is_on_side
        or case_access.side == app.side
        or Application.objects.filter(objection_to=app).exists()
    ):
        return None
    return {
        "due_on": app.respond_by,
        "decision_date": app.decision_date,
        "can_file": case_access.is_drafter,
    }


def court_view(app, user, objection):
    """What the bench needs on opening an application (#14.4)."""
    open_ = app.status in OPEN_STATUSES
    next_hearing = hearings.next_hearing(app.case_id)
    suggested = actions.suggested_date(app) if open_ else None
    task = None
    if app.status == S.PENDING_REVIEW and app.review_due_date:
        task = {
            "kind": "REVIEW",
            "due_date": app.review_due_date,
            "overdue": app.review_due_date < today(),
        }
    elif app.status == S.PENDING_DECISION and app.decision_date:
        task = {
            "kind": "DECIDE",
            "due_date": app.decision_date,
            "overdue": app.decision_date < today(),
        }
    live = ports.live_items_targeting([app.pk]).get(app.pk)
    order_actions = []
    if app.status == S.PENDING_REVIEW:
        order_actions = ["onboard", "defer", "dismiss"]
    elif app.status == S.PENDING_DECISION:
        order_actions = ["decide", "move_date"]
    return {
        "suggested_date": suggested,
        "order_actions": order_actions,
        "can_draft_order": ports.can_draft_order(user, app.case.court_id),
        "decision_hint": app.spec.decision_hint(app),
        "court": {
            "case_number": app.case.case_number or app.case.filing_number,
            "courtroom": app.case.court.name if app.case.court_id else None,
            "next_hearing": {
                "date": next_hearing.hearing_date,
                "purpose_label": next_hearing.purpose_label,
            }
            if next_hearing
            else None,
        },
        "task": task,
        "document": rendering.build(app),
        "pending_order": live,
    }


# Court queue (#14.4, #14.5) -----------------------------------------------------------


def court_queryset(user, court_id):
    """Submitted applications across a courtroom's cases, for its staff (#14.4).

    Annotated with ``closed_at`` (the deciding order or the expiry), whether a
    review was deferred and whether an objection was filed, so the queue needs
    no query per row.
    """
    if court_id is None or not ports.is_court_reader(user, court_id):
        return Application.objects.none()
    closing = ApplicationTransition.objects.filter(
        application_ref=OuterRef("pk"), action__in=CLOSING_ACTIONS
    ).order_by("-created_at")
    return (
        base_queryset()
        .filter(case__court_id=court_id, status__in=SUBMITTED_STATUSES)
        .exclude(application_type__code="OBJECTION")
        .annotate(
            closed_at=Subquery(closing.values("created_at")[:1]),
            review_deferred=Exists(
                ApplicationTransition.objects.filter(
                    application_ref=OuterRef("pk"), action=Action.DEFER_REVIEW
                )
            ),
            has_objection_flag=_submitted_objection_exists(),
        )
    )


def _submitted_objection_exists():
    return Exists(Application.objects.filter(objection_to=OuterRef("pk"), status=S.SUBMITTED))


def _band(app, day, live):
    if app.pk in live:
        return "signing"
    if app.status == S.PENDING_REVIEW:
        return "onboard" if app.review_due_date and app.review_due_date <= day else "upcoming"
    if app.status == S.PENDING_DECISION:
        return "decide" if app.decision_date and app.decision_date <= day else "upcoming"
    return None


def _due(app):
    if app.status == S.PENDING_REVIEW:
        return app.review_due_date
    if app.status == S.PENDING_DECISION:
        return app.decision_date
    return None


def _closed_on(app):
    """The day the deciding order or the expiry took effect (#14.5 closed / archive)."""
    closed_at = getattr(app, "closed_at", None) or app.updated_at
    return closed_at.astimezone(IST).date()


def court_queue(user, court_id, *, view=None, queue=None, filters=None):
    """The court's Applications screen (#14.5). Returns ``(rows, facets, today)``."""
    filters = filters or {}
    day = today()
    base = court_queryset(user, court_id)
    if queue in TYPE_QUEUES:
        base = base.filter(application_type__code__in=TYPE_QUEUES[queue])
    elif queue == "other":
        base = base.exclude(
            application_type__code__in=[c for codes in TYPE_QUEUES.values() for c in codes]
        )
    facets = {
        "type": [
            {"value": code, "label": label, "count": count}
            for code, label, count in base.values_list(
                "application_type__code", "application_type__label"
            )
            .annotate(count=Count("pk"))
            .values_list("application_type__code", "application_type__label", "count")
            .order_by("application_type__code")
        ],
        "stage": [],
    }
    queryset = _filter(base, {k: v for k, v in filters.items() if k in ("type",)})
    if filters.get("side"):
        queryset = queryset.filter(side=filters["side"])
    if filters.get("search"):
        queryset = _search(queryset, filters["search"])
    applications = list(queryset)
    live = ports.live_items_targeting([a.pk for a in applications])
    closed_days = conf.closed_view_days()
    cutoff = day - datetime.timedelta(days=closed_days)

    def in_view(app):
        if view in (None, ""):
            return True
        band = _band(app, day, live)
        if view == "all":
            return band is not None
        if view == "closed":
            return app.status in CLOSED_STATUSES and _closed_on(app) >= cutoff
        if view == "archive":
            return app.status in CLOSED_STATUSES and _closed_on(app) < cutoff
        return band == view

    rows = [a for a in applications if in_view(a)]
    ordering = filters.get("ordering")
    band_order = {"onboard": 0, "decide": 1, "signing": 2, "upcoming": 3}
    if view in ("closed", "archive"):
        rows.sort(key=_closed_on, reverse=True)
    elif ordering == "submitted_at":
        rows.sort(key=lambda a: a.submitted_at)
    elif ordering == "-submitted_at" or (queue and not view and not ordering):
        rows.sort(key=lambda a: a.submitted_at, reverse=True)
    elif ordering == "next_hearing":
        next_dates = {case_id: _next_hearing_date(case_id) for case_id in {a.case_id for a in rows}}
        rows.sort(key=lambda a: next_dates[a.case_id] or datetime.date.max)
    else:
        rows.sort(
            key=lambda a: (
                band_order.get(_band(a, day, live), 9) if view == "all" else 0,
                _due(a) or datetime.date.max,
                a.submitted_at,
            )
        )
    return rows, facets, day, live


def _next_hearing_date(case_id):
    hearing = hearings.next_hearing(case_id)
    return hearing.hearing_date if hearing else None


def _search(queryset, text):
    from apps.cases.selectors import search_case_ids

    text = text.strip()
    return queryset.filter(
        Q(application_number__icontains=text)
        | Q(earlier_application_number__icontains=text)
        | Q(application_type__label__icontains=text)
        | Q(case_id__in=search_case_ids(text))
    )


def queue_rows(applications, day, live, *, queue=None):
    """Serialisable court queue rows (#14.5), one batched summary call."""
    applications = list(applications)
    case_ids = {a.case_id for a in applications}
    summaries = get_case_summaries(case_ids)
    advocates = get_case_advocates(case_ids)
    rows = []
    for app in applications:
        summary = summaries.get(app.case_id)
        band = _band(app, day, live)
        due = _due(app)
        row = {
            "application_id": app.pk,
            "type": {"code": app.application_type.code, "label": app.application_type.label},
            "application_number": app.application_number,
            "earlier_application_number": app.earlier_application_number,
            "case": {
                "id": app.case_id,
                "case_number": summary.display_number if summary else "",
                "title": summary.title if summary else "",
                "stage": summary.stage if summary else None,
                "advocates": [
                    {"name": a.name, "side": a.side} for a in advocates.get(app.case_id, [])
                ],
            },
            "side": app.side,
            "filed_by": _user_name(app.raised_by),
            "submitted_at": app.submitted_at,
            "band": band,
            "task": {
                "kind": "REVIEW" if app.status == S.PENDING_REVIEW else "DECIDE",
                "due_date": due,
                "overdue": due < day,
                "due_today": due == day,
                "deferred": app.status == S.PENDING_REVIEW
                and getattr(app, "review_deferred", False),
            }
            if due
            else None,
            "status_line": {
                "status": app.status,
                "objection_status": ObjectionStatus.FILED
                if getattr(app, "has_objection_flag", False)
                else objection_status(app, day=day),
                "review_due_date": app.review_due_date,
                "decision_date": app.decision_date,
                "respond_by": app.respond_by,
            },
            "pending_order": live.get(app.pk),
            "outcome": app.outcome or (app.status if app.status == S.EXPIRED else None),
            "deciding_order": {"id": app.deciding_order_id, "number": None}
            if app.deciding_order_id
            else None,
        }
        if queue == "rescheduling" and app.hearing_id:
            hearing = hearings.get_hearing(app.hearing_id)
            row["hearing"] = (
                {"date": hearing.hearing_date, "purpose_label": hearing.purpose_label}
                if hearing
                else None
            )
            row["proposed_date"] = app.data.get("proposed_date")
        rows.append(row)
    return rows


def court_counts(user, court_id):
    """Counts per view and per type-cut queue; only onboard and decide are badged (#14.5).

    Queue counts are open work, as the task counts they stand in for (0011
    ``/tasks/counts/``): a closed application is in its queue's list, not its count.
    """
    day = today()
    applications = list(court_queryset(user, court_id))
    live = ports.live_items_targeting([a.pk for a in applications])
    cutoff = day - datetime.timedelta(days=conf.closed_view_days())
    views = dict.fromkeys(COURT_VIEWS, 0)
    for app in applications:
        band = _band(app, day, live)
        if band:
            views[band] += 1
            views["all"] += 1
        elif app.status in CLOSED_STATUSES:
            views["closed" if _closed_on(app) >= cutoff else "archive"] += 1
    queues = dict.fromkeys((*TYPE_QUEUES, "other"), 0)
    typed = {code: name for name, codes in TYPE_QUEUES.items() for code in codes}
    for app in applications:
        if _band(app, day, live):
            queues[typed.get(app.application_type.code, "other")] += 1
    return {
        "today": day,
        "views": views,
        "queues": queues,
        "badge": views["onboard"] + views["decide"],
    }
