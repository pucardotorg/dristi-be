"""Users app configuration."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class UsersConfig(AppConfig):
    """Users app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.users"
    verbose_name = "Users"

    def ready(self):
        """Register the settings checks, request hooks and approver seeding."""
        from . import hooks  # noqa: F401
        from .services import checks  # noqa: F401
        from .services.approvers import seed_superuser_approvers

        # sender=self: runs once per migrate, after every app's migrations.
        post_migrate.connect(
            seed_superuser_approvers, sender=self, dispatch_uid="users.seed_superuser_approvers"
        )
