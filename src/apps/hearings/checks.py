"""Startup checks for hearings configuration (spec 0023 #4)."""

from django.core.checks import Error, Tags, register
from django.db import DatabaseError

from . import conf


@register(Tags.database)
def check_business_date_override(app_configs, databases=None, **kwargs):
    """Refuse a pinned business date in production (run with ``check --database``)."""
    if not databases or not conf.is_production():
        return []
    from apps.core.models import Configuration

    try:
        pinned = (
            Configuration.objects.active()
            .filter(config_set=conf.CONFIG_SET, config_key="business_date_override")
            .exclude(config_value="")
            .exists()
        )
    except DatabaseError:
        return []
    if not pinned:
        return []
    return [
        Error(
            "hearings.business_date_override is set in production; it is a test-only setting.",
            hint="Deactivate or clear the hearings.business_date_override configuration entry.",
            id="hearings.E001",
        )
    ]
