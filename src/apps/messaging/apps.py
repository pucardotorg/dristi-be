"""Messaging app configuration."""

from django.apps import AppConfig


class MessagingConfig(AppConfig):
    """Messaging app config."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.messaging"
    verbose_name = "Messaging"
