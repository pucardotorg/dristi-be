"""DSC eSign addon app configuration."""

from django.apps import AppConfig


class DSCESignConfig(AppConfig):
    """Installed only so the addon can register system checks.

    It contributes no models, migrations, URLs, admin or middleware.
    """

    name = "addon.dsc_esign"
    label = "dsc_esign"
    verbose_name = "DSC eSign"

    def ready(self):
        """Register the addon's system checks."""

        from . import checks  # noqa: F401
