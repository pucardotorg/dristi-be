"""PDF app configuration."""

from django.apps import AppConfig


class PdfConfig(AppConfig):
    """PDF app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pdf"
    verbose_name = "PDF"

    def ready(self):
        """Register settings checks and config-cache invalidation hooks."""
        from . import checks, signals  # noqa: F401
