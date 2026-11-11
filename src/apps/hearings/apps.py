"""Hearings app configuration."""

from django.apps import AppConfig


class HearingsConfig(AppConfig):
    """Hearings app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.hearings"
    verbose_name = "Hearings"
