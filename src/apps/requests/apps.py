"""Requests app configuration."""

from django.apps import AppConfig


class RequestsConfig(AppConfig):
    """Requests app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.requests"
    verbose_name = "Requests"

    # Post-approval hooks are owned and registered by the consuming apps
    # (see apps.requests.hooks), so this app imports no request types itself.
