"""Files app configuration."""

from django.apps import AppConfig


class FilesConfig(AppConfig):
    """Files app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.files"
    verbose_name = "Files"
