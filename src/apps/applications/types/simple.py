"""Types with no fields of their own, and the shared availability rules (spec 0033 #3.1, #3.4).

Case Settlement, Case Withdrawal, Delay Condonation, Absent Application and
Reopen Evidence put their reason in *Application details*; Case Transfer and
Generic add one field; an Objection holds its target in ``objection_to``.
"""

from .. import ports
from ..enums import Side
from .base import ApplicationTypeSpec, Problems


def side_only(side):
    """The type is offered only to a drafter on ``side`` (#6.1)."""

    def reason(ctx):
        if ctx.side != side:
            return f"Only the {Side(side).label.lower()}'s side can raise this application."
        return None

    return reason


class SimpleType(ApplicationTypeSpec):
    """A type whose reason goes in *Application details*."""


class CaseSettlement(SimpleType):
    code = "CASE_SETTLEMENT"
    label = "Case Settlement"


class CaseWithdrawal(SimpleType):
    code = "CASE_WITHDRAWAL"
    label = "Case Withdrawal"


class AbsentApplication(SimpleType):
    code = "ABSENT_APPLICATION"
    label = "Absent Application"


class ReopenEvidence(SimpleType):
    code = "REOPEN_EVIDENCE"
    label = "Reopen Evidence"


class DelayCondonation(SimpleType):
    """On acceptance **and** rejection, ends the Delay Condonation stage (#12.2)."""

    code = "DELAY_CONDONATION"
    label = "Delay Condonation"
    has_workflow = True
    runs_on_reject = True

    def unavailable_reason(self, ctx):
        return side_only(Side.COMPLAINANT)(ctx)

    def on_accept(self, app, *, order_id, values):
        ports.dispatch_case_event(app.case_id, "DCA_DECIDED")
        return {"case_event": "DCA_DECIDED"}

    def on_reject(self, app, *, order_id):
        ports.dispatch_case_event(app.case_id, "DCA_DECIDED")


class CaseTransfer(ApplicationTypeSpec):
    """``requested_court``; the current court is filled at render (#3.4)."""

    code = "CASE_TRANSFER"
    label = "Case Transfer"
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"requested_court": {"type": "string", "maxLength": 255}},
    }

    def form_context(self, ctx):
        from apps.cases.models import Case

        court = Case.objects.select_related("court").get(pk=ctx.case_id).court
        return {"current_court": court.name if court else ""}

    def validate(self, app, *, complete):
        problems = Problems()
        if complete and not (app.data.get("requested_court") or "").strip():
            problems.missing("data.requested_court")
        return problems.items

    def render_entries(self, app):
        court = app.case.court
        return [
            {"term": "Current court", "value": court.name if court else ""},
            {"term": "Requested court", "value": app.data.get("requested_court", "")},
        ]


class Generic(ApplicationTypeSpec):
    """``title`` is the application's heading (#3.4)."""

    code = "GENERIC"
    label = "Generic"
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"title": {"type": "string", "maxLength": 255}},
    }

    def validate(self, app, *, complete):
        problems = Problems()
        if complete and not (app.data.get("title") or "").strip():
            problems.missing("data.title")
        return problems.items

    def render_title(self, app):
        return (app.data.get("title") or "").strip() or app.application_type.label


class Objection(SimpleType):
    """Against one undecided application of the other side (#9, ``ALC-37``).

    Created only through the objection endpoint (or ``POST`` with
    ``objection_to``); ``services.objections`` decides availability, so the
    generic type list offers it only while there is something to object to.
    """

    code = "OBJECTION"
    label = "Objection"

    def unavailable_reason(self, ctx):
        from ..services.objections import objectable

        if ctx.side is None or not objectable(ctx.case_id, ctx.side).exists():
            return "There is no application of the other side to object to."
        return None

    def form_context(self, ctx):
        from ..services.objections import objectable

        if ctx.side is None:
            return {"objectable_applications": []}
        return {
            "objectable_applications": [
                {
                    "id": str(app.pk),
                    "type": app.application_type.label,
                    "application_number": app.application_number,
                    "status": app.status,
                    "decision_date": app.decision_date,
                    "respond_by": app.respond_by,
                }
                for app in objectable(ctx.case_id, ctx.side).select_related("application_type")
            ]
        }

    def render_title(self, app):
        target = app.objection_to
        if target is None:
            return self.label
        return f"Objection to {target.application_type.label} application {target.application_number or ''}".strip()
