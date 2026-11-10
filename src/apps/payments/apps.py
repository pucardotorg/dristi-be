"""Payments app configuration."""

from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    """Payments app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payments"
    verbose_name = "Payments"

    def ready(self):
        """Register the provider configuration checks (spec 0017 #9.3)."""

        from . import checks  # noqa: F401
