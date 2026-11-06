"""e-GRAS payment gateway addon app configuration (spec 0022 #1)."""

from django.apps import AppConfig


class EGRASPaymentGatewayConfig(AppConfig):
    """Installed only so the addon can register system checks.

    It contributes no models, migrations, URLs, admin, middleware or
    ``errors.py``. The explicit ``label`` keeps the app registry key short and
    stable even though the dotted ``name`` lives under ``addon``.
    """

    name = "addon.egras_payment_gateway"
    label = "egras_payment_gateway"
    verbose_name = "e-GRAS Payment Gateway"

    def ready(self):
        """Register the addon's system checks and the config-cache reset."""

        from . import (
            checks,  # noqa: F401
            config,  # noqa: F401
        )
