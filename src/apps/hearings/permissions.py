"""Who may read and act on hearings (spec 0023 #1.2, #10.5).

* Court staff of a court hold at least one hearing role there and see every
  hearing of it, in every status (``RLE-06``). Each action needs its own role
  (``403 E10025``).
* Parties (``case_ids_visible_to``) read their cases' hearings, never a
  provisional or released one, and act on none (``403 E10018``).
* Anyone else, court staff of another court included, is told the hearing
  does not exist (``404 E00105``).

Roles are read for the hearing's court only (``RLE-02b``), through
``ports.court_roles``.
"""

from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.cases.selectors import case_ids_visible_to

from . import errors, ports
from .enums import HearingRole, HearingStatus
from .models import Hearing

# The role each action needs in the hearing's court (#10.1).
ACTION_ROLES = {
    "start": HearingRole.HEARING_CONTROLLER,
    "pass_over": HearingRole.HEARING_CONTROLLER,
    "end": HearingRole.HEARING_CONTROLLER,
    "bulk_action": HearingRole.HEARING_CONTROLLER,
    "reorder": HearingRole.HEARING_CONTROLLER,
    "reschedule": HearingRole.NEXT_HEARING_SETTER,
    "cancel": HearingRole.NEXT_HEARING_SETTER,
    "bulk_reschedule": HearingRole.NEXT_HEARING_SETTER,
    "calendar_entry": HearingRole.NEXT_HEARING_SETTER,
    "mark_attendance": HearingRole.ORDER_DATA_FILLER,
}
# Never shown to parties: a date is not announced before its order is triggered (PUB-07).
UNANNOUNCED = (HearingStatus.PROVISIONAL, HearingStatus.RELEASED)


def court_roles(user, court_id):
    """Return the hearing roles ``user`` holds in the court."""
    return ports.court_roles(user, court_id)


def require_staff(user, court_id):
    """Return the caller's roles in the court; refuse anyone with none (``403 E10018``)."""
    roles = court_roles(user, court_id)
    if not roles:
        raise BusinessError(errors.NOT_COURT_STAFF)
    return roles


def require_role(roles, action):
    """Refuse court staff without the role ``action`` needs (``403 E10025``)."""
    role = ACTION_ROLES[action]
    if role not in roles:
        raise BusinessError(
            errors.ROLE_REQUIRED,
            f"You need the {role.label.lower()} role in this court to do this.",
        )


def require_action(user, court_id, action):
    """Court staff of the court holding the role ``action`` needs; return their roles."""
    roles = require_staff(user, court_id)
    require_role(roles, action)
    return roles


def allowed_for_roles(actions, roles):
    """The ``allowed_actions`` the caller's roles permit (#10.2, ``CLS-06``)."""
    return [action for action in actions if ACTION_ROLES.get(action) in roles]


def is_party(user, case_id):
    """Whether ``user`` has an active relationship with the case."""
    return case_ids_visible_to(user).filter(pk=case_id).exists()


def visible_hearing(user, hearing_id):
    """Return ``(hearing, roles)`` for a hearing the caller may see, or raise ``NotFound``.

    ``roles`` is empty for a party.
    """
    hearing = Hearing.objects.select_related("purpose", "court").filter(pk=hearing_id).first()
    if hearing is None:
        raise NotFound("Hearing not found.")
    roles = court_roles(user, hearing.court_id)
    if roles:
        return hearing, roles
    if hearing.status not in UNANNOUNCED and is_party(user, hearing.case_id):
        return hearing, frozenset()
    raise NotFound("Hearing not found.")


def actionable_hearing(user, hearing_id, action):
    """Return ``(hearing, roles)`` for an action on the hearing.

    Not visible: ``404``. A party: ``403 E10018``. Court staff without the
    action's role: ``403 E10025``.
    """
    hearing, roles = visible_hearing(user, hearing_id)
    if not roles:
        raise BusinessError(errors.NOT_COURT_STAFF)
    require_role(roles, action)
    return hearing, roles


def case_access(user, case_id, case_court_id):
    """Return the caller's roles for a case's hearings: staff of its court, or a party (empty).

    Raises ``NotFound`` for anyone else, so the case is not revealed.
    """
    roles = court_roles(user, case_court_id) if case_court_id else frozenset()
    if roles:
        return roles
    if is_party(user, case_id):
        return frozenset()
    raise NotFound("Case not found.")
