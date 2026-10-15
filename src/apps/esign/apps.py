"""eSign app configuration."""

from django.apps import AppConfig


class ESignConfig(AppConfig):
    """eSign app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.esign"
    verbose_name = "eSign"

    def ready(self):
        """Register the settings checks once the app registry is populated."""

        from . import checks  # noqa: F401
