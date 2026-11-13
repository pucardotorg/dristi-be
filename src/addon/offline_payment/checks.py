"""Django system checks for the offline payment configuration (spec 0032 #13.3).

Every check is silent when the addon is installed but ``"offline"`` is not a
registered payment provider, so environments that do not offer it need no
``OFFLINE_PAYMENT_*`` values.
"""

from django.core.checks import Error, Warning, register

from apps.payments import conf as payments_conf

from . import constants
from .config import is_registered, resolve_config

CHECK_PREFIX = "offline_payment"


@register()
def check_offline_payment_configuration(app_configs, **kwargs):
    """Validate the offline settings when the provider is registered."""

    if not is_registered():
        return []

    messages = [
        Error(message, id=f"{CHECK_PREFIX}.{check_id}")
        for check_id, message in resolve_config().validate()
    ]

    offered = {payments_conf.default_provider(), *payments_conf.selectable_providers()}
    if constants.PROVIDER_NAME not in offered:
        messages.append(
            Warning(
                "The offline payment provider is registered but neither the default nor "
                "selectable; it can only finish requests already in flight.",
                hint="Add 'offline' to PAYMENT_SELECTABLE_PROVIDERS to offer it to payers.",
                id=f"{CHECK_PREFIX}.W001",
            )
        )
    return messages
