"""Objections (spec 0033 #9, ``ALC-11``-``ALC-13``, ``ALC-24``, ``ALC-37``).

An objection is an application of type ``OBJECTION`` against **one** undecided
application of the other side, at most one per application. It goes through
filing like any application and ends at ``SUBMITTED``. The *File objection*
task opens for the other side only when an order asks it to respond; the task
is derived from the target's ``respond_by`` until 0011 lands (#1.2).
"""

import datetime

from django.db import IntegrityError, transaction
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.payments.models import Demand
from apps.payments.services.demands import DemandService

from .. import access, errors, ports
from ..enums import OPEN_STATUSES, ApplicationStatus
from ..models import OBJECTION_CODE, Application, ApplicationType
from . import common, notifications
from .calendar import today
from .common import Action

S = ApplicationStatus


def objectable(case_id, side):
    """The other side's undecided applications with no objection yet (``ALC-37``)."""
    return (
        Application.objects.filter(
            case_id=case_id, status__in=OPEN_STATUSES, objection__isnull=True
        )
        .exclude(side=side)
        .exclude(application_type__code=OBJECTION_CODE)
    )


def start_objection(target_id, user, *, case_id=None, data=None):
    """``POST /applications/{id}/objection/`` (#9): create, or return the caller's own draft.

    Returns ``(objection, created)``.
    """
    data = data or {}
    with transaction.atomic():
        target = (
            Application.objects.select_for_update(of=("self",))
            .select_related("application_type", "case")
            .filter(pk=target_id)
            .first()
        )
        if target is None or (case_id is not None and str(target.case_id) != str(case_id)):
            raise NotFound("Application not found.")
        if not access.can_see(target, user):
            raise NotFound("Application not found.")
        ctx = ports.case_access(target.case_id, user)
        if not ctx.is_drafter or ctx.side == target.side or target.is_objection:
            raise BusinessError(errors.OBJECTION_NOT_ALLOWED)
        existing = Application.objects.filter(objection_to=target).first()
        if existing is not None:
            if access.in_drafting_circle(existing, user, ctx):
                return existing, False
            raise BusinessError(errors.OBJECTION_TAKEN)
        if target.status not in OPEN_STATUSES:
            raise BusinessError(errors.TARGET_NOT_PENDING)
        if not ports.is_on_file(target.case):
            raise BusinessError(errors.CASE_NOT_ON_FILE)
        row = ApplicationType.objects.active().filter(code=OBJECTION_CODE).first()
        if row is None:
            raise BusinessError(errors.TYPE_NOT_AVAILABLE, field="application_type")
        objection = Application(
            case=target.case,
            application_type=row,
            status=S.DRAFT,
            side=ctx.side,
            objection_to=target,
            created_by=user,
            updated_by=user,
        )
        from . import drafting

        drafting.apply_initial_fields(objection, ctx, data)
        try:
            with transaction.atomic():
                objection.save()
        except IntegrityError as exc:
            # Two drafters at once (#16.8): the loser gets the winner's draft, or E13022.
            existing = Application.objects.filter(objection_to=target).first()
            if existing is not None and access.in_drafting_circle(existing, user, ctx):
                return existing, False
            raise BusinessError(errors.OBJECTION_TAKEN) from exc
        common.log(objection, Action.CREATE, user, from_status="", to_status=S.DRAFT)
    return objection, True


def after_date_set(application, *, previous_respond_by):
    """Open, re-date or leave the other side's *File objection* after a date is set (#9).

    The first ask is the other side's first notification (``ALC-12``); a later
    move tells it the new date when a response is still asked.
    """
    if not application.objections_invited or application.respond_by is None:
        return
    if application.respond_by < today():
        return
    if previous_respond_by is None or previous_respond_by < today():
        ports.tasks.open("file_objection", application, due_date=application.respond_by)
        notifications.response_requested(application)
    elif previous_respond_by != application.respond_by:
        ports.tasks.reschedule("file_objection", application, due_date=application.respond_by)


def close_open_objection(target):
    """The target is decided, dismissed or expired: an unsubmitted objection can go no further (#9).

    Its *File objection* task closes (``NO_LONGER_RELEVANT``) and its unpaid
    demand is cancelled; the draft itself stays, to be deleted.
    """
    ports.tasks.expire("file_objection", target, reason="NO_LONGER_RELEVANT")
    objection = Application.objects.filter(objection_to=target).exclude(status=S.SUBMITTED).first()
    if objection is None or not objection.demand_id:
        return
    demand = Demand.objects.filter(pk=objection.demand_id).first()
    if demand is not None:
        try:
            DemandService.cancel_demand(
                demand, reason="Application objected to is no longer pending"
            )
        except BusinessError:
            # A payment in flight settles later; the receiver then refuses to submit (E13023).
            pass


def close_windows():
    """``WINDOW_CLOSED``: expire *File objection* tasks whose ``respond_by`` has passed (#9, #16.6).

    Nothing changes on the application: a missed deadline changes nothing by
    itself (``ALC-13``). Returns how many windows closed.
    """
    # The windows that closed at the end of yesterday: each is expired once, not nightly.
    passed = Application.objects.filter(
        status=S.PENDING_DECISION,
        objections_invited=True,
        respond_by=today() - datetime.timedelta(days=1),
        objection__isnull=True,
    )
    count = 0
    for application in passed.only("pk"):
        ports.tasks.expire("file_objection", application, reason="WINDOW_CLOSED")
        count += 1
    return count
