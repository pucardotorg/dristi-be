"""Dristi requests app configuration."""

from django.apps import AppConfig


class DristiRequestsConfig(AppConfig):
    """Dristi requests app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dristi_requests"
    verbose_name = "Dristi Requests"

    # Post-approval hooks are owned and registered by the consuming apps (see
    # apps.dristi_requests.hooks), so this app imports no request types itself.
