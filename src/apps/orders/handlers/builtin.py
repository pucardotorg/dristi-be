"""The handlers owned by orders (spec 0039 #9.3): dates, cognizance, submissions, cost, batta."""

import datetime
import logging

from django.db import transaction

from apps.cases.selectors import order_context
from apps.hearings import selectors as hearing_selectors
from apps.hearings.services import calendar

from .. import ports
from ..enums import OrderStatus
from ..models import OrderItem
from .base import OrderItemHandler, Problem, RunResult

logger = logging.getLogger(__name__)

COMPLAINANT = "COMPLAINANT"
ACCUSED = "ACCUSED"


class NoWorkflowHandler(OrderItemHandler):
    """The default for an item with no workflow of its own: its effect, if any, is the stage step."""

    item_codes = ()

    def execute(self, ctx, values, *, run_id):
        return RunResult("DONE")


def triggered_items(case_id, *codes, exclude_order_id=None):
    """Return the triggered order items of the case with one of ``codes``, oldest first."""
    queryset = OrderItem.objects.filter(
        order__case_id=case_id,
        order__status=OrderStatus.TRIGGERED,
        item_type__code__in=codes,
    ).order_by("order__triggered_at", "position")
    if exclude_order_id:
        queryset = queryset.exclude(order_id=exclude_order_id)
    return queryset


class HearingDateHandler(OrderItemHandler):
    """Scheduling and Rescheduling of hearing date: the next hearing's items (#6.4, #9.2).

    The date itself is held and confirmed by the ``HEARING`` step, so ``execute``
    does nothing. People do not add these items: they follow from the order's
    next hearing outside a hearing, and are not offered in one (``ORD-08``,
    ``ORD-09``, ``NXT-03``).
    """

    item_codes = ("SCHEDULING_OF_HEARING_DATE", "RESCHEDULING_OF_HEARING_DATE")

    def unavailable_reason(self, ctx):
        if ctx.hearing_id:
            return "IN_HEARING", "Set the next date under Next hearing."
        rescheduling = ctx.item_id is None and self._is_rescheduling
        if rescheduling and not hearing_selectors.has_scheduled_hearing(ctx.case_id):
            return "NO_HEARING_SCHEDULED", "The case has no scheduled hearing to move."
        if ctx.source and ctx.source != "SYSTEM":
            return "FOLLOWS_NEXT_HEARING", "Set the date under Next hearing."
        return None

    _is_rescheduling = False

    def execute(self, ctx, values, *, run_id):
        return RunResult("DONE", {"done_by": "HEARING"})


class SchedulingHandler(HearingDateHandler):
    item_codes = ("SCHEDULING_OF_HEARING_DATE",)


class ReschedulingHandler(HearingDateHandler):
    item_codes = ("RESCHEDULING_OF_HEARING_DATE",)
    _is_rescheduling = True

    def defaults(self, ctx):
        scheduled = hearing_selectors.next_hearing(ctx.case_id)
        if scheduled is None:
            return {}
        return {
            "hearing_purpose": scheduled.purpose_code,
            "original_hearing_date": scheduled.hearing_date.isoformat(),
        }


class CognizanceHandler(OrderItemHandler):
    """Cognizance: refused once cognizance has been taken (#6.1)."""

    item_codes = ("COGNIZANCE",)

    def unavailable_reason(self, ctx):
        if triggered_items(ctx.case_id, "COGNIZANCE", exclude_order_id=ctx.order_id).exists():
            return "COGNIZANCE_TAKEN", "Cognizance has already been taken in this case."
        return None

    def execute(self, ctx, values, *, run_id):
        return RunResult("DONE")


class MoveOutOfLprHandler(OrderItemHandler):
    """Moving out of the Long Pending Register: only for a case in it (#6.1).

    Until 0011 gives cases a workflow stage, the register is read from the case's
    own triggered orders: the last of *Moving to* and *Moving out of* wins.
    """

    item_codes = ("MOVE_OUT_OF_LONG_PENDING_REGISTER",)

    def unavailable_reason(self, ctx):
        last = (
            triggered_items(
                ctx.case_id,
                "MOVE_TO_LONG_PENDING_REGISTER",
                "MOVE_OUT_OF_LONG_PENDING_REGISTER",
                exclude_order_id=ctx.order_id,
            )
            .order_by("-order__triggered_at", "-position")
            .select_related("item_type")
            .first()
        )
        if last is None or last.item_type.code != "MOVE_TO_LONG_PENDING_REGISTER":
            return "NOT_IN_LPR", "The case is not in the Long Pending Register."
        return None

    def execute(self, ctx, values, *, run_id):
        return RunResult("DONE")


class MandatorySubmissionHandler(OrderItemHandler):
    """Mandatory submissions and responses: a citizen task for the directed side (#9.3)."""

    item_codes = ("MANDATORY_SUBMISSIONS",)

    def validate(self, ctx, values, *, complete):
        problems = []
        deadline = values.get("deadline")
        if deadline:
            try:
                if datetime.date.fromisoformat(deadline) < calendar.business_date():
                    problems.append(
                        Problem("values.deadline", "IN_PAST", "The deadline cannot be in the past.")
                    )
            except ValueError:
                pass
        return problems if complete else []

    def execute(self, ctx, values, *, run_id):
        reference = ports.open_item_task(
            ctx.order_id,
            ctx.item_id,
            "mandatory_submission",
            side=values.get("party_type", ""),
            due=values.get("deadline"),
            detail={
                "document_type": values.get("document_type"),
                "document_details": values.get("document_details"),
            },
        )
        return RunResult("DONE", {"task": reference})


class CostHandler(OrderItemHandler):
    """Cost: a ``COST`` demand on the case and a *Pay cost* task for the paying side (#9.3)."""

    item_codes = ("COST",)

    def validate(self, ctx, values, *, complete):
        if values.get("paying_party") and values.get("paying_party") == values.get(
            "receiving_party"
        ):
            return [
                Problem(
                    "values.receiving_party",
                    "SAME_AS_PAYER",
                    "The receiving party cannot be the paying party.",
                )
            ]
        return []

    def execute(self, ctx, values, *, run_id):
        from apps.payments.enums import ChargeType, ReferenceType
        from apps.payments.models import Demand
        from apps.payments.services.demands import DemandService

        # Demand has no unique reference, so the item's row serialises lookup and creation:
        # a second overlapping run waits, then finds the first run's demand.
        with transaction.atomic():
            OrderItem.objects.select_for_update().get(pk=ctx.item_id)
            demand = Demand.objects.filter(
                reference_type=ReferenceType.ORDER, reference_id=str(ctx.item_id)
            ).first()
            if demand is None:
                demand = DemandService.raise_demand(
                    case=ctx.case_id,
                    reference_type=ReferenceType.ORDER,
                    reference_id=str(ctx.item_id),
                    user_id=paying_user_id(ctx.case_id, values.get("paying_party")),
                    due_date=_end_of_day(values.get("pay_by")),
                    metadata={
                        "order_id": str(ctx.order_id),
                        "receiving_party": values.get("receiving_party"),
                        "paying_party": values.get("paying_party"),
                    },
                    items=[
                        {
                            "charge_type": ChargeType.COST,
                            "description": "Cost ordered by the court",
                            "quantity": 1,
                            "unit_amount": values["amount"],
                        }
                    ],
                )
        reference = ports.open_item_task(
            ctx.order_id,
            ctx.item_id,
            "pay_cost",
            side=values.get("paying_party", ""),
            due=values.get("pay_by"),
            detail={"demand_id": str(demand.pk)},
        )
        return RunResult("DONE", {"demand_id": str(demand.pk), "task": reference})


def _end_of_day(iso_date):
    """The payment deadline as the last moment of that day, in the court's time zone."""
    if not iso_date:
        return None
    day = datetime.date.fromisoformat(iso_date)
    return datetime.datetime.combine(day, datetime.time(23, 59, 59), tzinfo=calendar.IST)


def paying_user_id(case_id, side):
    """Return the user who acts for ``side`` on the case: its first party with an account."""
    from apps.cases.models import CaseParticipant

    roles = {COMPLAINANT: ("COMPLAINANT", "POA_HOLDER"), ACCUSED: ("ACCUSED",)}.get(side, ())
    participant = (
        CaseParticipant.objects.active()
        .filter(case_id=case_id, role__in=roles, person__user__isnull=False)
        .select_related("person")
        .order_by("ordinal")
        .first()
    )
    return participant.person.user_id if participant else None


class WitnessBattaHandler(OrderItemHandler):
    """Witness batta: a task for the paying side, closed when they confirm payment (#9.3).

    The money is not paid through the system. The witness defaults to the case's
    one witness, where there is exactly one (``VAR-03``).
    """

    item_codes = ("WITNESS_BATTA",)

    def defaults(self, ctx):
        witnesses = order_context(ctx.case_id).witnesses
        return {"witness": str(witnesses[0].id)} if len(witnesses) == 1 else {}

    def execute(self, ctx, values, *, run_id):
        reference = ports.open_item_task(
            ctx.order_id,
            ctx.item_id,
            "witness_batta",
            side=values.get("paying_party", ""),
            due=values.get("pay_by"),
            detail={"amount": values.get("amount"), "witness": values.get("witness")},
        )
        return RunResult("DONE", {"task": reference})


BUILTIN = (
    SchedulingHandler,
    ReschedulingHandler,
    CognizanceHandler,
    MoveOutOfLprHandler,
    MandatorySubmissionHandler,
    CostHandler,
    WitnessBattaHandler,
)
