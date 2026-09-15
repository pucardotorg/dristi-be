"""Users app configuration."""

from django.apps import AppConfig


class UsersConfig(AppConfig):
    """Users app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
    verbose_name = "Users"

    def ready(self):
        """Register the settings checks once the app registry is populated."""
        from . import checks  # noqa: F401
