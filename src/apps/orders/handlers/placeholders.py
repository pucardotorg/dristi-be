"""Stand-ins for the handlers of modules that are not built yet (spec 0039 #9.3).

``apps.processes`` (spec 0028) owns the process items and ``apps.applications``
(spec 0033) the application items and *Bail*. Until they register their own
handler, these keep the catalogue consistent: the item can be drafted and its
order data completed, and its step fails with ``HANDLER_MODULE_NOT_AVAILABLE``
when the order is triggered. The step stays ``FAILED`` and is retried from the
admin once the module has registered its handler (#9.2). A placeholder is
replaced, never duplicated, by the real registration.
"""

from .. import ports
from .base import OrderItemHandler, Problem, RunResult

MODULE_NOT_AVAILABLE = "HANDLER_MODULE_NOT_AVAILABLE"


class ModulePendingHandler(OrderItemHandler):
    """Fails honestly instead of pretending an unbuilt module did its work."""

    placeholder = True
    module = ""

    def execute(self, ctx, values, *, run_id):
        return RunResult("FAILED", {"module": self.module}, MODULE_NOT_AVAILABLE)


class ProcessPendingHandler(ModulePendingHandler):
    """The six process items, until ``apps.processes`` registers them (spec 0028)."""

    module = "processes"
    item_codes = (
        "ISSUE_OF_SUMMONS",
        "ISSUE_OF_WARRANTS",
        "ISSUE_OF_NOTICE",
        "ISSUE_OF_PROCLAMATION",
        "ISSUE_OF_ATTACHMENT",
        "ISSUE_OF_MISCELLANEOUS_PROCESS",
    )

    def defaults(self, ctx):
        """Every accused is the default recipient; the side taking steps follows (``AUT-05``, ``AUT-02``)."""
        from apps.cases.models import ParticipantRole
        from apps.cases.selectors import order_context

        accused = order_context(ctx.case_id).of_role(ParticipantRole.ACCUSED)
        if not accused:
            return {}
        return {
            "party_names": [str(party.id) for party in accused],
            "party_taking_steps": "COMPLAINANT",
        }

    def validate(self, ctx, values, *, complete):
        if not complete:
            return []
        problems = []
        for index, recipient in enumerate(values.get("recipients") or []):
            if not recipient.get("channels"):
                problems.append(
                    Problem(
                        f"values.recipients[{index}].channels",
                        "REQUIRED",
                        "Choose at least one delivery channel.",
                    )
                )
        return problems


class ApplicationPendingHandler(ModulePendingHandler):
    """The application items and Bail, until ``apps.applications`` registers them (spec 0033)."""

    module = "applications"
    item_codes = (
        "ACCEPT_APPLICATION",
        "REJECT_APPLICATION",
        "DISMISS_APPLICATION",
        "ACCEPTANCE_OF_BAIL",
        "BAIL",
    )

    def validate_target(self, ctx):
        # Applications are not modelled yet, so the target can be checked for shape
        # only (the service has already required a UUID).
        return (
            []
            if ctx.target_id
            else [Problem("target_id", "REQUIRED", "Choose the application this item applies to.")]
        )


class WithdrawalPendingHandler(ModulePendingHandler):
    """Withdrawal of case may arise from an application; its decision belongs to applications."""

    module = "applications"
    item_codes = ("WITHDRAWAL_OF_CASE",)

    def execute(self, ctx, values, *, run_id):
        # Withdrawal ends the case through the STAGE step alone; only an application
        # decision (reached from one) needs the applications module.
        if not ctx.target_id:
            return RunResult("DONE")
        return super().execute(ctx, values, run_id=run_id)


PLACEHOLDERS = (ProcessPendingHandler, ApplicationPendingHandler, WithdrawalPendingHandler)

__all__ = ["PLACEHOLDERS", "MODULE_NOT_AVAILABLE", "ports"]
