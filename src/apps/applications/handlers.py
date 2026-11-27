"""The ``APPLICATION_ACTION`` order item handler for spec 0025 (spec 0033 #8.1).

Written against 0025 #1.2's ``OrderItemHandler`` hooks. ``apps.orders`` is not
built (#1.2), so ``register_with_orders`` registers it only when
``apps.orders.handlers.registry`` is importable; until then the admin action
*Record order on application* runs the same ``services.actions.apply``.
"""

import logging
from importlib import import_module

from .models import Application
from .services import actions

logger = logging.getLogger(__name__)

ITEM_CODE = "APPLICATION_ACTION"
TARGET_TYPE = "APPLICATION"


class ApplicationActionHandler:
    """Hooks the order module calls for catalogue item #27 *Application action*."""

    item_codes = (ITEM_CODE,)

    def _application(self, ctx):
        if getattr(ctx, "target_type", "") != TARGET_TYPE or not getattr(ctx, "target_id", None):
            return None
        return (
            Application.objects.select_related("application_type", "case")
            .filter(pk=ctx.target_id)
            .first()
        )

    def unavailable_reason(self, ctx):
        application = self._application(ctx)
        if application is None:
            return None
        return actions.unavailable_reason(application)

    def validate_target(self, ctx):
        """The target is a submitted application of the order's case (``ITM-04``)."""
        application = self._application(ctx)
        if application is None or application.case_id != ctx.case_id or application.is_objection:
            return [
                actions.Problem("target_id", actions.INVALID, "Choose an application of this case.")
            ]
        if actions.unavailable_reason(application):
            return [
                actions.Problem(
                    "target_id", actions.APPLICATION_NOT_OPEN, "The application is not open."
                )
            ]
        return []

    def defaults(self, ctx):
        application = self._application(ctx)
        return actions.defaults(application) if application is not None else {}

    def validate(self, ctx, values, *, complete):
        application = self._application(ctx)
        if application is None:
            return self.validate_target(ctx)
        return actions.validate(
            application, values, complete=complete, moves_hearing=_moves_hearing(values)
        )

    def summary(self, ctx, values):
        application = self._application(ctx)
        return actions.summary(application, values) if application is not None else ""

    def execute(self, ctx, values, *, run_id):
        """Apply the triggered order (#8.4); idempotent on the order and on ``run_id``."""
        return actions.apply(
            ctx.target_id,
            values,
            order_id=ctx.order_id,
            # 0025 #1.2's ItemContext carries no order date yet; use it once it does, so a
            # late trigger judges dates on the order's day, not the run's.
            order_date=getattr(ctx, "order_date", None),
            moves_hearing=_moves_hearing(values),
        )


def _moves_hearing(values):
    """Whether the same order moves the application's hearing (#8.2 ``HEARING_MOVE_REQUIRED``).

    The order module verifies the sibling *Rescheduling of hearing date* item and passes
    the result in the values; validation and execution read the same answer.
    """
    return bool(values.get("_moves_hearing"))


def register_with_orders():
    """Register the handler with 0025's registry when the orders module exists."""
    try:
        registry = import_module("apps.orders.handlers.registry")
    except ImportError:
        logger.debug("event=APPLICATION_HANDLER_NOT_REGISTERED reason=orders_not_installed")
        return False
    registry.register(ApplicationActionHandler())
    return True
