"""CDAC eSign addon app configuration."""

from django.apps import AppConfig


class CDACESignConfig(AppConfig):
    """Installed only so the addon can register system checks.

    It contributes no models, migrations, URLs, admin or middleware.
    """

    name = "addon.cdac_esign"
    label = "cdac_esign"
    verbose_name = "CDAC eSign"

    def ready(self):
        """Register the addon's system checks."""

        from . import checks  # noqa: F401
