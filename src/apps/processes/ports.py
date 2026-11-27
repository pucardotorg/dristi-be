"""Placeholders for the spec 0029 access contracts (spec 0028 #1.1, #2.2).

PLACEHOLDER. Spec 0028 checks court actions through
``apps.organizations.access.require`` and reads with
``selectors.is_court_reader``; spec 0029 is not built yet. Until it is, an
action is held through a Django group named after its code
(``process.sign``), for every process type and channel, at the deployment's
one establishment (``SCRUTINY_ESTABLISHMENT_ID``) and its courtrooms only,
the way hearings and scrutiny hold their roles. Every check in this module
goes through the functions below, so replacing this file is the whole
migration.
"""

import uuid

from django.conf import settings

from apps.api.errors import BusinessError
from apps.organizations.models import Organization

from . import court_actions, errors


def _served(court_id):
    """Whether ``court_id`` is the configured establishment or one of its courtrooms."""
    try:
        establishment = uuid.UUID(str(settings.SCRUTINY_ESTABLISHMENT_ID))
    except ValueError:
        return False
    if court_id is None:
        return False
    if str(court_id) == str(establishment):
        return True
    return Organization.objects.filter(pk=court_id, parent_id=establishment).exists()


def held_actions(user, court_id) -> frozenset[str]:
    """Return the process actions ``user`` is allowed at the court.

    PLACEHOLDER: unscoped; spec 0029's grants carry each action's scope.
    """
    if not user or not user.is_authenticated or not _served(court_id):
        return frozenset()
    names = user.groups.filter(name__in=court_actions.ALL).values_list("name", flat=True)
    return frozenset(names)


def can(user, action, court_id, *, process_type, channel) -> bool:
    """Whether ``user`` may take ``action`` on a process of this type and channel at the court."""
    return action in held_actions(user, court_id)


def require(user, action, court_id, *, process_type, channel):
    """Refuse a step the caller is not allowed (``403 E12015``)."""
    if not can(user, action, court_id, process_type=process_type, channel=channel):
        raise BusinessError(errors.PROCESS_ACTION_NOT_ALLOWED)


def is_court_reader(user, court_id) -> bool:
    """Whether ``user`` is staff of the courtroom, who reads all its processes (``RLE-06``).

    PLACEHOLDER: anyone holding a process action there; spec 0029 reads the
    courtroom's list (``CourtroomAssignment``).
    """
    return bool(held_actions(user, court_id))
