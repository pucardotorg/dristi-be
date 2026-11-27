"""Applications app configuration (spec 0033 #1)."""

from django.apps import AppConfig


class ApplicationsConfig(AppConfig):
    """Applications app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.applications"
    verbose_name = "Applications"

    def ready(self):
        """Register the types, checks, receivers, the e-sign authorizer and the order handler."""
        from apps.esign.constants import EntityType
        from apps.esign.permissions import register_entity_authorizer

        from . import checks, receivers, types  # noqa: F401
        from .handlers import register_with_orders
        from .services.signing import can_sign_application

        register_entity_authorizer(EntityType.APPLICATION.value, can_sign_application)
        register_with_orders()
