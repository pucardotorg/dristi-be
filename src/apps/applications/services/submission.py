"""Payment and submission (spec 0033 #6.8, #6.9, ``ALC-01``-``ALC-03``).

Filing ends only when the application is signed and, where its type carries a
fee, paid. A type with no fee skips Pending Payment. The demand is the fee's
snapshot: a later change to the configuration never changes it.
"""

import logging

from django.db import transaction

from apps.api.errors import BusinessError
from apps.payments.enums import ChargeType, ReferenceType
from apps.payments.services.demands import DemandService

from .. import conf, errors, ports
from ..enums import OPEN_STATUSES, ApplicationStatus
from ..models import Application
from . import common, notifications, numbering
from .calendar import next_working_day, today
from .common import Action

logger = logging.getLogger(__name__)

S = ApplicationStatus
OPEN_TARGET = OPEN_STATUSES


def fee_for(application):
    return conf.fee(ports.state_code(application.case), application.application_type.code)


def after_signature(application, actor, sign_metadata):
    """In the signing transaction: raise the fee's demand, or submit at once (#6.8)."""
    fee = fee_for(application)
    if fee > 0:
        demand = DemandService.raise_demand(
            case=application.case_id,
            reference_type=ReferenceType.APPLICATION,
            reference_id=str(application.pk),
            items=[
                {
                    "charge_type": ChargeType.APPLICATION_FEE,
                    "reference_type": ReferenceType.APPLICATION,
                    "reference_id": str(application.pk),
                    "description": f"{application.application_type.label} — application fee",
                    "quantity": 1,
                    "unit_amount": fee,
                }
            ],
            user_id=application.raised_by_id,
            actor=actor,
        )
        application.demand_id = demand.pk
        common.transition(
            application,
            Action.SIGN,
            actor,
            to_status=S.PENDING_PAYMENT,
            metadata=sign_metadata,
        )
        ports.tasks.complete("sign_application", application)
        ports.tasks.open(
            "pay_application_fee",
            application,
            users=ports.side_user_ids(application.case_id, application.side),
        )
        return application
    common.transition(application, Action.SIGN, actor, metadata=sign_metadata)
    ports.tasks.complete("sign_application", application)
    return submit(application, actor)


def on_payment_completed(sender, payment, demand, items, demand_paid, **kwargs):
    """``payment_completed`` receiver: submit the application whose demand is now paid (#6.8).

    Matched by the stored ``demand_id``, never by reference; idempotent, so a
    second delivery finds the application already past Pending Payment.
    """
    if not demand_paid:
        return
    with transaction.atomic():
        application = (
            Application.objects.select_for_update(of=("self",))
            .select_related("application_type", "case", "case__court")
            .filter(demand_id=demand.pk)
            .first()
        )
        if application is None or application.status != S.PENDING_PAYMENT:
            return
        if application.is_objection and application.objection_to.status not in OPEN_TARGET:
            # Paid after its target was decided (#9): nothing to submit to. The money is
            # the payments module's to refund; the objection stays here, to be deleted.
            logger.warning(
                "event=APPLICATION_OBJECTION_PAID_LATE application_id=%s", application.pk
            )
            return
        common.transition(application, Action.PAY, None, metadata={"payment_id": str(payment.pk)})
        ports.tasks.complete("pay_application_fee", application)
        submit(application, None)


def submit(application, actor):
    """Submit the locked application (#6.9)."""
    from .expiry import hearing_gone

    if application.is_objection and application.objection_to.status not in OPEN_TARGET:
        raise BusinessError(errors.TARGET_NOT_PENDING)
    application.submitted_at = common.now()
    numbering.allot_submission_number(application)
    if application.is_objection:
        numbering.guard_number_clash(
            lambda: common.transition(application, Action.SUBMIT, actor, to_status=S.SUBMITTED)
        )
        ports.tasks.complete("file_objection", application.objection_to)
        notifications.objection_filed(application)
        logger.info("event=APPLICATION_SUBMITTED application_id=%s objection=1", application.pk)
        return application
    state = ports.state_code(application.case)
    application.review_due_date = next_working_day(
        application.case.court_id, today(), state_code=state
    )
    numbering.guard_number_clash(
        lambda: common.transition(application, Action.SUBMIT, actor, to_status=S.PENDING_REVIEW)
    )
    ports.tasks.open("review_application", application, due_date=application.review_due_date)
    notifications.submitted(application)
    reason = hearing_gone(application) if application.spec.expires_with_hearing else None
    if reason is not None:
        from .expiry import expire

        expire(application, reason)
    return application
