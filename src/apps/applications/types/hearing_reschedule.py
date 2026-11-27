"""Advance / Prepone and Postpone (spec 0033 #3.4, #12.2, #13).

``hearing_id`` is set by the server at creation to the case's next scheduled
hearing; the client never chooses it. Acceptance moves the hearing through the
accepting order (#8.2 ``HEARING_MOVE_REQUIRED``), so ``on_accept`` only checks
the move happened and records it.
"""

import datetime

from apps.api import errors as api_errors
from apps.hearings import selectors as hearings

from .. import conf
from .base import ApplicationTypeSpec, Problems


class HearingReschedule(ApplicationTypeSpec):
    needs_hearing = True
    expires_with_hearing = True
    has_workflow = True
    # Advance asks for an earlier date than the hearing; Postpone a later one.
    earlier = True
    data_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "reason_code": {"type": "string", "maxLength": 64},
            "proposed_date": {"type": "string", "format": "date", "maxLength": 10},
        },
    }

    def unavailable_reason(self, ctx):
        if not hearings.has_scheduled_hearing(ctx.case_id):
            return "The case has no hearing scheduled."
        return None

    def form_context(self, ctx):
        from ..services.drafting import scheduled_hearing

        hearing = scheduled_hearing(ctx.case_id)
        return {
            "hearing": _hearing_dict(hearing),
            "reschedule_reasons": conf.reschedule_reasons(),
        }

    def validate(self, app, *, complete):
        problems = Problems()
        data = app.data
        reason = data.get("reason_code")
        codes = {item.get("code") for item in conf.reschedule_reasons()}
        if reason and reason not in codes:
            problems.add("data.reason_code", api_errors.INVALID_CHOICE)
        proposed = _date(data.get("proposed_date"))
        if data.get("proposed_date") and proposed is None:
            problems.add("data.proposed_date", api_errors.INVALID, "Enter a date as YYYY-MM-DD.")
        if proposed is not None:
            from apps.hearings.services.calendar import business_date

            hearing = hearings.get_hearing(app.hearing_id) if app.hearing_id else None
            if proposed < business_date():
                problems.add(
                    "data.proposed_date", api_errors.INVALID, "Choose today or a later date."
                )
            elif hearing is not None and (
                (self.earlier and proposed >= hearing.hearing_date)
                or (not self.earlier and proposed <= hearing.hearing_date)
            ):
                word = "before" if self.earlier else "after"
                problems.add(
                    "data.proposed_date",
                    api_errors.INVALID,
                    f"Choose a date {word} the hearing on {hearing.hearing_date.isoformat()}.",
                )
        if complete:
            if not reason:
                problems.missing("data.reason_code")
            if not data.get("proposed_date"):
                problems.missing("data.proposed_date")
        return problems.items

    def render_entries(self, app):
        hearing = hearings.get_hearing(app.hearing_id) if app.hearing_id else None
        labels = {item.get("code"): item.get("label") for item in conf.reschedule_reasons()}
        return [
            {
                "term": "Initial hearing date",
                "value": hearing.hearing_date.isoformat() if hearing else "",
            },
            {"term": "Purpose of hearing", "value": hearing.purpose_label if hearing else ""},
            {
                "term": "Reason for rescheduling",
                "value": labels.get(app.data.get("reason_code"), app.data.get("reason_code", "")),
            },
            {"term": "Proposed hearing date", "value": app.data.get("proposed_date", "")},
        ]

    def on_accept(self, app, *, order_id, values):
        """The accepting order moved the hearing (0025 #9.2 runs it first); record where to."""
        hearing = hearings.get_hearing(app.hearing_id)
        return {
            "hearing_id": str(app.hearing_id),
            "hearing_date": hearing.hearing_date.isoformat() if hearing else None,
            "summary": (
                f"Hearing rescheduled to {hearing.hearing_date:%d %b %Y}" if hearing else ""
            ),
        }


class AdvanceHearing(HearingReschedule):
    code = "ADVANCE_HEARING"
    label = "Advance / Prepone"
    earlier = True


class PostponeHearing(HearingReschedule):
    code = "POSTPONE_HEARING"
    label = "Postpone"
    earlier = False


def _date(value):
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError:
        return None


def _hearing_dict(hearing):
    if hearing is None:
        return None
    return {
        "id": str(hearing.id),
        "hearing_date": hearing.hearing_date.isoformat(),
        "purpose_label": hearing.purpose_label,
    }
