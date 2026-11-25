"""Processes app configuration."""

from django.apps import AppConfig


class ProcessesConfig(AppConfig):
    """Summons, warrants and every other process (spec 0028)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.processes"
    verbose_name = "Processes"

    def ready(self):
        """Subscribe to payments and hearings (#6.3, #8.6)."""
        from . import receivers  # noqa: F401
