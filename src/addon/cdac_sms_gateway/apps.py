"""CDAC SMS gateway app configuration."""

from django.apps import AppConfig


class CDACSMSGatewayConfig(AppConfig):
    """Installed only so the gateway can register system checks."""

    name = "addon.cdac_sms_gateway"
    label = "cdac_sms_gateway"
    verbose_name = "CDAC SMS Gateway"

    def ready(self):
        """Register the addon's system checks."""

        from . import checks  # noqa: F401
