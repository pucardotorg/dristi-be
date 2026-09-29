"""Simple requests app configuration."""

from django.apps import AppConfig


class SimpleRequestsConfig(AppConfig):
    """Simple requests app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.simple_requests"
    verbose_name = "Simple Requests"

    # Post-approval hooks are owned and registered by the consuming apps (see
    # apps.simple_requests.hooks), so this app imports no request types itself.
