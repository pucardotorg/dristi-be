"""Django system checks for the e-GRAS configuration (spec 0022 #9.3).

Every check is silent when the addon is installed but e-GRAS is not a registered
payment provider, so local and CI environments need no e-GRAS codes.
"""

from django.core.checks import Error, Warning, register

from apps.payments.checks import is_production_settings
from apps.payments.enums import ChargeType

from .config import is_active_provider, resolve_config

_CODE_IDS = {
    "EGRAS_PAYMENT_URL": "egras_payment_gateway.E002",
    "EGRAS_VERIFY_URL": "egras_payment_gateway.E002",
    "EGRAS_RETURN_URL": "egras_payment_gateway.E002",
    "EGRAS_DTO": "egras_payment_gateway.E003",
    "EGRAS_STO": "egras_payment_gateway.E003",
    "EGRAS_DDO": "egras_payment_gateway.E003",
    "EGRAS_DEPT_CODE": "egras_payment_gateway.E003",
    "EGRAS_OFFICE_NAME": "egras_payment_gateway.E003",
    "EGRAS_SCHEME_MAP": "egras_payment_gateway.E004",
    "EGRAS_MAX_SCHEMES": "egras_payment_gateway.E004",
    "EGRAS_BANK_OPTIONS": "egras_payment_gateway.E005",
    "EGRAS_DEFAULT_BANK": "egras_payment_gateway.E005",
    "EGRAS_APPLICATION_PREFIX": "egras_payment_gateway.E006",
    "EGRAS_PENDING_HORIZON": "egras_payment_gateway.E007",
}


@register()
def check_egras_configuration(app_configs, **kwargs):
    """Validate the e-GRAS settings when this addon is the active provider."""

    if not is_active_provider():
        return []

    config = resolve_config()

    # Behind the kill switch only configuration that verification still needs
    # must hold; but validating the whole block early is harmless and catches a
    # deployment that forgot to turn e-GRAS back on correctly.
    messages = [
        Error(message, id=_CODE_IDS.get(setting_name, "egras_payment_gateway.E001"))
        for setting_name, message in config.validate()
    ]

    messages.extend(_check_charge_type_coverage(config))

    if is_production_settings() and not config.verify_ssl:
        messages.append(
            Error(
                "EGRAS_VERIFY_SSL must be enabled in production; the GRN status lookup is "
                "the only proof a payment was collected.",
                id="egras_payment_gateway.E008",
            )
        )

    return messages


def _check_charge_type_coverage(config):
    """Warn about charge types with no scheme mapping (spec 0022 #9.3).

    A charge whose head of account is unmapped fails at payment time with
    ``EGRAS_SCHEME_UNMAPPED``. Surfacing it at deploy time turns a payer-facing
    failure into an operator task. Mappings may also be keyed by
    ``account_head``, which cannot be enumerated here, so this is a warning.
    """

    mapped = set(config.scheme_map or {})
    missing = [charge.value for charge in ChargeType if charge.value not in mapped]
    if not missing:
        return []
    return [
        Warning(
            "EGRAS_SCHEME_MAP has no entry for charge types: " + ", ".join(sorted(missing)) + ". "
            "Charges on an unmapped head of account will fail at payment time unless their "
            "account_head is mapped instead.",
            id="egras_payment_gateway.W001",
        )
    ]
