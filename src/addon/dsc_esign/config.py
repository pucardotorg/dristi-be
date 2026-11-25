"""DSC eSign configuration (spec 0038 #11).

Flat ``DSC_ESIGN_*`` settings, namespaced to the addon so nothing DSC-specific
leaks into the generic ``ESIGN_*`` space. Read live (no cache) so test overrides
take effect without a reset.
"""

from dataclasses import dataclass

from django.conf import settings

from . import constants


@dataclass(frozen=True)
class DSCESignConfig:
    """Immutable snapshot of the DSC eSign configuration."""

    agent_url: str = ""
    require_registered_cert: bool = False
    identity_resolver: str = ""
    trust_roots: str = ""
    hash_algorithm: str = "SHA256"


def resolve_config() -> DSCESignConfig:
    """Return the current DSC configuration from settings."""

    return DSCESignConfig(
        agent_url=getattr(settings, "DSC_ESIGN_AGENT_URL", "") or "",
        require_registered_cert=bool(getattr(settings, "DSC_ESIGN_REQUIRE_REGISTERED_CERT", False)),
        identity_resolver=getattr(settings, "DSC_ESIGN_IDENTITY_RESOLVER", "") or "",
        trust_roots=getattr(settings, "DSC_ESIGN_TRUST_ROOTS", "") or "",
        hash_algorithm=str(getattr(settings, "PDF_SIGNATURE_HASH_ALGORITHM", "SHA256")).upper(),
    )


def is_registered() -> bool:
    """Whether the DSC provider is registered (spec 0038 #11.1).

    Read from settings directly so the addon depends only on the contract, not on
    the domain's provider behaviour.
    """

    providers = getattr(settings, "ESIGN_PROVIDERS", {}) or {}
    if providers:
        return constants.PROVIDER_NAME in providers or constants.PROVIDER_PATH in providers.values()
    return getattr(settings, "ESIGN_PROVIDER", "") == constants.PROVIDER_PATH
