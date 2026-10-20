"""Address app configuration."""

from django.apps import AppConfig


class AddressConfig(AppConfig):
    """Address app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.address"
    verbose_name = "Address"
