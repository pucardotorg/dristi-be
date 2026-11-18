"""Notifications app configuration (spec 0031)."""

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    """Notifications app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "Notifications"

    def ready(self):
        """Register startup settings checks for the notifications app."""
        from . import checks  # noqa: F401
