"""Orders app configuration."""

from django.apps import AppConfig


class OrdersConfig(AppConfig):
    """Orders app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.orders"
    verbose_name = "Orders"

    def ready(self):
        """Register the checks, the built-in handlers and the ``ORDER`` e-sign authorizer."""
        from apps.esign import permissions as esign_permissions

        from . import handlers
        from .handlers import checks  # noqa: F401
        from .permissions import can_sign_via_esign

        handlers.register_builtin()
        esign_permissions.register_entity_authorizer("ORDER", can_sign_via_esign)
