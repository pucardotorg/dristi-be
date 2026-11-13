"""Startup validation of ``SCRUTINY_ESTABLISHMENT_ID`` (spec 0024 #2.2).

Court roles count only at that establishment (``ports.roles_held``), so a
missing or wrong value closes scrutiny rather than opening it to every court.
These checks say so at startup instead of leaving every court user with 404s.
"""

import uuid

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.db import DatabaseError

HINT = (
    "Set SCRUTINY_ESTABLISHMENT_ID to the organization id of this deployment's court establishment."
)


@register()
def check_establishment_setting(app_configs, **kwargs):
    """Warn when the establishment is unset; refuse a value that is not a UUID."""
    value = settings.SCRUTINY_ESTABLISHMENT_ID
    if not value:
        return [
            Warning(
                "SCRUTINY_ESTABLISHMENT_ID is not set: nobody holds a court role, so every "
                "scrutiny and registration endpoint is closed.",
                hint=HINT,
                id="scrutiny.W001",
            )
        ]
    try:
        uuid.UUID(str(value))
    except ValueError:
        return [
            Error(
                f"SCRUTINY_ESTABLISHMENT_ID must be a UUID, got {value!r}.",
                hint=HINT,
                id="scrutiny.E001",
            )
        ]
    return []


@register(Tags.database)
def check_establishment_exists(app_configs, databases=None, **kwargs):
    """Refuse an establishment that is not an active organization (run with ``check --database``)."""
    if not databases or not settings.SCRUTINY_ESTABLISHMENT_ID:
        return []
    from apps.organizations.models import Organization

    from .ports import configured_establishment

    establishment_id = configured_establishment()
    if establishment_id is None:
        return []
    try:
        found = Organization.objects.active().filter(pk=establishment_id).exists()
    except DatabaseError:
        # Not migrated yet: ``migrate`` runs database checks before it creates the tables.
        return []
    if found:
        return []
    return [
        Error(
            f"SCRUTINY_ESTABLISHMENT_ID {establishment_id} is not an active organization.",
            hint=HINT,
            id="scrutiny.E002",
        )
    ]
