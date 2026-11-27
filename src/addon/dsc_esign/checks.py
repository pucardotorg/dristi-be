"""Django system checks for the DSC eSign configuration (spec 0038 #11.1).

Silent unless the DSC provider is registered, so environments that do not use it
need no DSC settings.
"""

from django.core.checks import Error, Warning, register

from apps.esign.checks import is_production_settings

from .config import is_registered, resolve_config


@register()
def check_dsc_esign_configuration(app_configs, **kwargs):
    """Validate the DSC settings when the provider is registered."""

    if not is_registered():
        return []

    config = resolve_config()
    messages = []

    if not config.agent_url:
        messages.append(
            Error(
                "DSC_ESIGN_AGENT_URL is required when the DSC provider is registered.",
                id="dsc_esign.E001",
            )
        )
    elif not config.agent_url.startswith(("http://", "https://")):
        messages.append(Error("DSC_ESIGN_AGENT_URL must be an absolute URL.", id="dsc_esign.E002"))

    if config.require_registered_cert and not config.identity_resolver:
        message = (
            "DSC_ESIGN_REQUIRE_REGISTERED_CERT is enabled but DSC_ESIGN_IDENTITY_RESOLVER "
            "is not set; signatures cannot be bound to a registered DSC."
        )
        messages.append(
            Error(message, id="dsc_esign.E003")
            if is_production_settings()
            else Warning(message, id="dsc_esign.W001")
        )

    # Without trust roots, an untrusted (self-signed) certificate is only accepted
    # when DSC_ESIGN_ALLOW_UNTRUSTED_CERT is explicitly set — never in production.
    if not config.trust_roots and not config.allow_untrusted_cert:
        message = (
            "DSC_ESIGN_TRUST_ROOTS is not set; DSC certificates cannot be verified against "
            "the India CCA chain. Set it, or (non-production only) enable "
            "DSC_ESIGN_ALLOW_UNTRUSTED_CERT to accept untrusted certificates."
        )
        messages.append(
            Error(message, id="dsc_esign.E004")
            if is_production_settings()
            else Warning(message, id="dsc_esign.W002")
        )
    elif config.allow_untrusted_cert and is_production_settings():
        messages.append(
            Error(
                "DSC_ESIGN_ALLOW_UNTRUSTED_CERT must not be enabled in production.",
                id="dsc_esign.E005",
            )
        )

    return messages
