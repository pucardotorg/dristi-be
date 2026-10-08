"""Core app configuration."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Core app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

    def ready(self):
        """Build the business-rule engine registry (spec 0019 #4.6).

        Only instantiates the adapters, so a missing engine dependency fails
        at startup. It must not touch the database: ready() also runs during
        ``migrate`` and ``check``.
        """
        from .rules.engines import build_registry

        build_registry()
