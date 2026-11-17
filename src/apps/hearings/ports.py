"""Placeholders for the contracts other modules do not offer yet (spec 0023 #1.2).

PLACEHOLDER. Spec 0023 reads court roles through
``apps.organizations.selectors.court_roles(user, court_id)``, backed by a
per-courtroom membership (``CourtMember``, or spec 0026's role assignments).
Neither exists yet. Until one does, roles are Django groups named after
``HearingRole``, the way scrutiny holds its roles (``apps/scrutiny/ports.py``),
and they count only at the deployment's one establishment
(``SCRUTINY_ESTABLISHMENT_ID``) and its courtrooms. Every hearings permission
goes through ``court_roles`` below, so replacing this module is the whole
migration.
"""

import uuid

from django.conf import settings

from apps.organizations.models import Organization

from .enums import HearingRole


def configured_establishment():
    """Return the id of the establishment this deployment serves, or None if unset or malformed."""
    try:
        return uuid.UUID(str(settings.SCRUTINY_ESTABLISHMENT_ID))
    except ValueError:
        return None


def _in_establishment(court_id):
    """Whether ``court_id`` is the configured establishment or one of its courtrooms."""
    establishment = configured_establishment()
    if establishment is None or court_id is None:
        return False
    if str(court_id) == str(establishment):
        return True
    return Organization.objects.filter(pk=court_id, parent_id=establishment).exists()


def court_roles(user, court_id):
    """Return the hearing roles ``user`` holds in the court; none in any other court.

    PLACEHOLDER: the user's ``HearingRole`` groups, at the configured
    establishment's courts only.
    """
    if not user or not user.is_authenticated or not _in_establishment(court_id):
        return frozenset()
    names = user.groups.filter(name__in=HearingRole.values).values_list("name", flat=True)
    return frozenset(HearingRole(name) for name in names)
