"""Startup validation of ``SCRUTINY_ESTABLISHMENT_ID`` (spec 0024 #2.2, #2.5).

Every case entering scrutiny goes to that establishment (``ports.establishment_id``),
so a missing or wrong value refuses every submission for scrutiny. These checks
say so at startup instead of leaving filers to find out after paying.
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
                "SCRUTINY_ESTABLISHMENT_ID is not set: every case submitted for scrutiny is "
                "refused (E09019).",
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
    """Refuse a value that is not an active court establishment (run with ``check --database``).

    Its courtrooms are the ones the Scrutiny officer chooses from (``SCR-16``),
    and its roles are the ones that act on the case (spec 0029 #10.1).
    """
    if not databases or not settings.SCRUTINY_ESTABLISHMENT_ID:
        return []
    from apps.organizations import selectors as court

    from .ports import configured_establishment

    establishment_id = configured_establishment()
    if establishment_id is None:
        return []
    try:
        establishment = court.active_establishment_of(establishment_id)
    except DatabaseError:
        # Not migrated yet: ``migrate`` runs database checks before it creates the tables.
        return []
    if establishment is not None and establishment.pk == establishment_id:
        return []
    return [
        Error(
            f"SCRUTINY_ESTABLISHMENT_ID {establishment_id} is not an active court establishment.",
            hint=HINT,
            id="scrutiny.E002",
        )
    ]
