"""Requests app configuration."""

from django.apps import AppConfig


class RequestsConfig(AppConfig):
    """Requests app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.requests"
    verbose_name = "Requests"

    def ready(self):
        """Import request-type modules so their post-approval hooks register."""
        from .request_types import lawyer_bar  # noqa: F401
