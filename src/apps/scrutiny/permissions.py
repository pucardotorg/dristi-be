"""Who may read and act on a filing in scrutiny (spec 0024 #2.2, #8.4; spec 0029 #10.1).

Reading is not an action: anyone allowed any scrutiny or registration action
at the case's establishment sees its filings; anyone else is told the case
does not exist (``404 E00105``). Each action is then checked by the service
that takes it (``403 E09008``).
"""

from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.organizations import selectors as court

from . import court_actions as actions
from . import errors, ports
from .models import ScrutinyRound


def actions_held(user, establishment_id):
    """Return the action codes ``user`` is allowed at the establishment."""
    return court.actions_of(user, establishment_id)


def _holds_any(user, establishment_id, stage_actions):
    held = actions_held(user, establishment_id)
    return any(action.code in held for action in stage_actions)


def require_court_reader(user, stage_actions, establishment_id=None):
    """Return the ids of the establishments a list covers, refusing ``E09008`` when there are none.

    ``stage_actions`` is the list's duty (``SCRUTINY_STAGE`` or
    ``REGISTRATION_STAGE``). Without ``establishment_id``, the list covers
    every establishment where the caller is allowed one of them; with it, just
    that one, refused where the caller is allowed none of them there.
    """
    if establishment_id is not None:
        if not _holds_any(user, establishment_id, stage_actions):
            raise BusinessError(errors.ROLE_REQUIRED)
        return [establishment_id]
    ids = list(court.establishments_of(user, stage_actions).values_list("pk", flat=True))
    if not ids:
        raise BusinessError(errors.ROLE_REQUIRED)
    return ids


def court_case(case_id, user):
    """Return ``(case, latest round)`` for a court reader, or raise ``NotFound``.

    A reader is allowed any scrutiny or registration action at the latest
    round's establishment, so officers keep the cases they forwarded on their
    *Closed* tab. A case that never reached scrutiny has no round and no
    establishment, so it is not found either.
    """
    latest = (
        ScrutinyRound.objects.select_related("case")
        .filter(case_id=case_id)
        .order_by("-created_at")
        .first()
    )
    if latest is None or not _holds_any(user, latest.establishment_id, actions.ALL):
        raise NotFound("Case not found.")
    return latest.case, latest


def filing_case(case_id, user):
    """Return the case for its filing side — filer, complainant, POA holder, their advocate.

    For reads: staff holding ``cases.view_case`` may read it too.
    """
    return ports.filing_side_case(case_id, user)


def filing_case_for_action(case_id, user):
    """Return the case for its filing side to act on; viewing staff are told it does not exist."""
    return ports.filing_side_case_for_action(case_id, user)
