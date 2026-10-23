"""CMS app configuration"""

from django.apps import AppConfig


class CmsConfig(AppConfig):
    """Cms app configuration"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.cms"
    verbose_name = "CMS"
