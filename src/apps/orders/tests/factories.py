"""Builders for the orders tests."""

from apps.hearings.enums import HearingRole
from apps.hearings.services import courtroom as hearing_courtroom
from apps.hearings.tests.factories import (  # noqa: F401  (re-exported)
    TODAY,
    code,
    field,
    hold,
    make_case,
    make_court,
    make_user,
    schedule,
)
from apps.orders.enums import OrderRole


def all_roles():
    """Every role an order action needs, plus the hearing controller."""
    return (*OrderRole.values, HearingRole.HEARING_CONTROLLER.value)


def started_hearing(case, controller, date=TODAY, purpose="APPEARANCE"):
    """Schedule a hearing of ``case`` for ``date`` and start it; return the hearing."""
    hearing = schedule(case, date, purpose)
    return hearing_courtroom.start(hearing_id=hearing.pk, actor=controller, court_id=case.court_id)


def mark_roll(hearing, controller):
    """Mark everyone on the hearing's roll present, in person."""
    from apps.cases.selectors import get_attendance_roll

    marks = [
        {
            "attendee_type": entry.type,
            "participant_id": entry.participant_id,
            "mark": "PRESENT",
            "appearance_mode": "IN_PERSON",
        }
        for entry in get_attendance_roll(hearing.case_id)
    ]
    hearing_courtroom.set_attendance(hearing_id=hearing.pk, marks=marks, actor=controller)
