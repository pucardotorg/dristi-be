"""Parties app configuration."""

from django.apps import AppConfig


class PartiesConfig(AppConfig):
    """Parties app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.parties"
    verbose_name = "Parties"
