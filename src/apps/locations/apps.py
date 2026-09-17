"""Locations app configuration."""

from django.apps import AppConfig


class LocationsConfig(AppConfig):
    """Locations app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.locations"
    verbose_name = "Locations"
