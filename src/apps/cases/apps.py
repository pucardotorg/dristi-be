"""Cases app configuration."""

from django.apps import AppConfig


class CasesConfig(AppConfig):
    """Cases app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cases"
    verbose_name = "Cases"

    def ready(self):
        """Register the settings checks once the app registry is populated."""
        from .services import checks  # noqa: F401
