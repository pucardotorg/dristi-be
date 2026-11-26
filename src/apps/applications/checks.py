"""System checks (spec 0033 #3.2, #7)."""

from django.core.checks import Error, Tags, Warning, register
from django.db import DatabaseError


@register(Tags.models, "database")
def active_types_have_specs(app_configs=None, databases=None, **kwargs):
    """``applications.E001``: an active ``ApplicationType`` row with no registered spec."""
    if not databases:
        return []
    from .models import ApplicationType
    from .types import registry

    try:
        codes = list(ApplicationType.objects.active().values_list("code", flat=True))
    except DatabaseError:
        return []
    return [
        Error(
            f"Application type {code} is active but no spec is registered for it.",
            hint="Deactivate the row in admin, or register its spec in apps.applications.types.",
            id="applications.E001",
        )
        for code in codes
        if registry.get(code) is None
    ]


@register("database")
def numbering_configured(app_configs=None, databases=None, **kwargs):
    """``applications.W001``: the deployment's state has no submission number format (#7)."""
    if not databases:
        return []
    from . import conf

    try:
        state = conf.default_state_code()
        if conf.numbering(state)["submission_number_format"]:
            return []
    except DatabaseError:
        return []
    return [
        Warning(
            "No application submission_number_format is configured"
            + (f" for {state}." if state else "."),
            hint="Set it in the configuration store (set applications.<state>); "
            "until then applications cannot be submitted (E13028).",
            id="applications.W001",
        )
    ]
