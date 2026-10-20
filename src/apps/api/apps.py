"""API app configuration."""

from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class ApiConfig(AppConfig):
    """API app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.api"
    verbose_name = "API"

    def ready(self):
        """Import every app's ``errors`` module so the code catalogue is complete."""
        autodiscover_modules("errors")
