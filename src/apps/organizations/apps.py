"""Organizations app configuration."""

from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    """Organizations app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.organizations"
    verbose_name = "Organizations"

    def ready(self):
        """Discover every app's ``court_actions`` module and register the system checks.

        Owning modules declare their actions in ``<app>/court_actions.py``
        (spec 0029 #3.1); this app imports no court module, it discovers them
        the way Django admin discovers ``admin.py``.
        """
        from django.utils.module_loading import autodiscover_modules

        from . import checks  # noqa: F401

        autodiscover_modules("court_actions")
