"""Organizations app configuration."""

from django.apps import AppConfig


class OrganizationsConfig(AppConfig):
    """Organizations app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.organizations"
    verbose_name = "Organizations"
