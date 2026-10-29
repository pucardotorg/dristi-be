"""Who may read and act on a filing in scrutiny (spec 0024 #2.2, #8.4).

Reading is not a role: holders of any court role at the case's establishment
see its filings (``RLE-06``); anyone else is told the case does not exist
(``404 E00105``). Each action then needs its own role, which the services
check when it is taken (``403 E09008``).
"""

from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError

from . import errors, ports
from .models import ScrutinyRound


def court_roles(user, establishment_id):
    """Return the court roles ``user`` holds at the establishment."""
    if not user or not user.is_authenticated:
        return frozenset()
    return ports.roles_held(user, establishment_id)


def require_court_reader(user, establishment_id=None):
    """Refuse a list to anyone holding no court role (``E09008``)."""
    if not court_roles(user, establishment_id):
        raise BusinessError(errors.ROLE_REQUIRED)


def court_case(case_id, user):
    """Return ``(case, latest round)`` for a court reader, or raise ``NotFound``.

    A case that never reached scrutiny has no round and no establishment, so
    it is not found either.
    """
    latest = (
        ScrutinyRound.objects.select_related("case")
        .filter(case_id=case_id)
        .order_by("-created_at")
        .first()
    )
    if latest is None or not court_roles(user, latest.establishment_id):
        raise NotFound("Case not found.")
    return latest.case, latest
