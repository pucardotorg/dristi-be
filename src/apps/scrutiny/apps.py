"""Scrutiny app configuration."""

from django.apps import AppConfig


class ScrutinyConfig(AppConfig):
    """Scrutiny app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.scrutiny"
    verbose_name = "Scrutiny"
