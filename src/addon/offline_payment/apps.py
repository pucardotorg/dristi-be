"""Offline payment addon app configuration (spec 0032 #1)."""

from django.apps import AppConfig


class OfflinePaymentConfig(AppConfig):
    """Installed only so the addon can register system checks.

    It contributes no models, migrations, URLs, admin, middleware or
    ``errors.py``. The explicit ``label`` keeps the app registry key short and
    stable even though the dotted ``name`` lives under ``addon``.
    """

    name = "addon.offline_payment"
    label = "offline_payment"
    verbose_name = "Offline Payment"

    def ready(self):
        """Register the addon's system checks and the config-cache reset."""

        from . import (
            checks,  # noqa: F401
            config,  # noqa: F401
        )
