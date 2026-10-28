"""e-GRAS configuration loading (spec 0022 #9).

One deployment serves one state and collects into one department, so the
settings are flat ``EGRAS_*`` values read from the environment into a frozen,
cached :class:`EGRASConfig`. e-GRAS has no credential, so nothing needs
redacting; payer data is masked in logs instead (#11). The cache is cleared
automatically when an ``EGRAS_*`` setting changes, which keeps tests honest, as
``CDACConfig`` does in spec 0013.
"""

import re
from dataclasses import dataclass, field
from datetime import timedelta
from functools import lru_cache

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver

from . import constants

# Required settings as ``(setting_name, attribute)`` pairs (spec 0022 #9.2).
REQUIRED_SETTINGS = (
    ("EGRAS_PAYMENT_URL", "payment_url"),
    ("EGRAS_VERIFY_URL", "verify_url"),
    ("EGRAS_RETURN_URL", "return_url"),
    ("EGRAS_DEPT_CODE", "dept_code"),
    ("EGRAS_DTO", "dto"),
    ("EGRAS_STO", "sto"),
    ("EGRAS_DDO", "ddo"),
    ("EGRAS_SCHEME_MAP", "scheme_map"),
    ("EGRAS_BANK_OPTIONS", "bank_options"),
)

HTTPS_URL = re.compile(r"^https://\S+$")
PREFIX_RE = re.compile(r"^[A-Za-z0-9]{1,2}$")

# e-GRAS marks a transaction failed on the 8th day when the bank never reports,
# so a provider horizon shorter than this would fail live payments (#6.4).
MIN_PENDING_HORIZON_DAYS = 8

# The generic callback path ``apps.payments`` registers for this provider
# (spec 0017 #9.6); ``EGRAS_RETURN_URL`` must point at it.
CALLBACK_PATH_SUFFIX = f"/providers/{constants.PROVIDER_NAME}/_callback"


@dataclass(frozen=True)
class BankOption:
    """One NIC-issued bank/UPI choice offered to the payer (spec 0022 #4.6)."""

    code: str
    label: str
    group: str = ""


@dataclass(frozen=True)
class EGRASConfig:
    """Immutable snapshot of the e-GRAS configuration."""

    payment_url: str = ""
    verify_url: str = ""
    return_url: str = ""
    dept_code: str = ""
    dto: str = ""
    sto: str = ""
    ddo: str = ""
    office_name: str = ""
    user_id: str = "guest"
    scheme_map: dict = field(default_factory=dict)
    max_schemes: int = 4
    bank_options: tuple[BankOption, ...] = ()
    default_bank: str = ""
    application_prefix: str = "DR"
    remarks_template: str = "Dristi {demand_numbers}"
    payer_fallback_city: str = "NA"
    payer_fallback_address: str = "NA"
    payer_fallback_pincode: str = "000000"
    timeout: int = 15
    verify_ssl: bool = True
    pending_horizon: timedelta = timedelta(days=9)
    not_found_grace: timedelta = timedelta(hours=2)
    enabled: bool = True

    @property
    def effective_office_name(self) -> str:
        """``EGRAS_OFFICE_NAME`` if set, else the 8-char ``DTO + STO + DDO``."""

        return self.office_name or f"{self.dto}{self.sto}{self.ddo}"

    def validate(self) -> list[tuple[str, str]]:
        """Return ``(setting_name, message)`` configuration problems (#9.3)."""

        problems = []
        for setting_name, attribute in REQUIRED_SETTINGS:
            if not getattr(self, attribute):
                problems.append((setting_name, f"{setting_name} is required."))

        for setting_name, value in (
            ("EGRAS_PAYMENT_URL", self.payment_url),
            ("EGRAS_VERIFY_URL", self.verify_url),
            ("EGRAS_RETURN_URL", self.return_url),
        ):
            if value and not HTTPS_URL.match(value):
                problems.append((setting_name, f"{setting_name} must be an absolute https:// URL."))

        if self.return_url and not self.return_url.endswith(CALLBACK_PATH_SUFFIX):
            problems.append(
                (
                    "EGRAS_RETURN_URL",
                    f"EGRAS_RETURN_URL must end with {CALLBACK_PATH_SUFFIX!r} so e-GRAS "
                    "returns the browser to the payments callback endpoint.",
                )
            )

        problems.extend(self._validate_office_codes())
        problems.extend(self._validate_schemes())
        problems.extend(self._validate_banks())

        if not PREFIX_RE.match(self.application_prefix or ""):
            problems.append(
                (
                    "EGRAS_APPLICATION_PREFIX",
                    "EGRAS_APPLICATION_PREFIX must be 1-2 alphanumeric characters.",
                )
            )

        if self.pending_horizon < timedelta(days=MIN_PENDING_HORIZON_DAYS):
            problems.append(
                (
                    "EGRAS_PENDING_HORIZON",
                    f"EGRAS_PENDING_HORIZON must be at least {MIN_PENDING_HORIZON_DAYS} days; "
                    "e-GRAS only declares failure on the 8th day.",
                )
            )

        return problems

    def _validate_office_codes(self):
        for setting_name, value, length, digits in (
            ("EGRAS_DTO", self.dto, 2, True),
            ("EGRAS_STO", self.sto, 2, True),
            ("EGRAS_DDO", self.ddo, 4, False),
            ("EGRAS_DEPT_CODE", self.dept_code, 3, False),
        ):
            if not value:
                continue
            if len(value) != length or (digits and not value.isdigit()):
                kind = f"{length} digits" if digits else f"{length} characters"
                yield (setting_name, f"{setting_name} must be {kind}.")

        # The default office name is DTO+STO+DDO (8 chars), but NIC may issue a
        # shorter explicit value — the v3.6 sample posts a 5-char Officename.
        # So accept up to 8 characters rather than requiring exactly 8.
        office = self.effective_office_name
        if office and len(office) > 8:
            yield (
                "EGRAS_OFFICE_NAME",
                "The office name (EGRAS_OFFICE_NAME, else DTO+STO+DDO) must be at most 8 characters.",
            )

    def _validate_schemes(self):
        for key, code in (self.scheme_map or {}).items():
            if not constants.SCHEME_CODE_RE.match(str(code)):
                yield (
                    "EGRAS_SCHEME_MAP",
                    f"EGRAS_SCHEME_MAP[{key!r}] = {code!r} is not a 17-character scheme code "
                    "(NNNN-NN-NNN-NN-NN).",
                )
        if isinstance(self.max_schemes, bool) or not isinstance(self.max_schemes, int):
            yield ("EGRAS_MAX_SCHEMES", "EGRAS_MAX_SCHEMES must be an integer.")
        elif self.max_schemes < 1:
            yield ("EGRAS_MAX_SCHEMES", "EGRAS_MAX_SCHEMES must be at least 1.")

    def _validate_banks(self):
        codes = [bank.code for bank in self.bank_options]
        if len(codes) != len(set(codes)):
            yield ("EGRAS_BANK_OPTIONS", "EGRAS_BANK_OPTIONS codes must be unique.")
        if self.default_bank and self.default_bank not in codes:
            yield (
                "EGRAS_DEFAULT_BANK",
                "EGRAS_DEFAULT_BANK must be one of the EGRAS_BANK_OPTIONS codes.",
            )


def _bank_options(raw) -> tuple[BankOption, ...]:
    """Coerce the JSON ``EGRAS_BANK_OPTIONS`` list into ``BankOption``s."""

    options = []
    for entry in raw or ():
        if isinstance(entry, BankOption):
            options.append(entry)
        else:
            options.append(
                BankOption(
                    code=str(entry.get("code", "")),
                    label=str(entry.get("label", "")),
                    group=str(entry.get("group", "")),
                )
            )
    return tuple(options)


@lru_cache(maxsize=1)
def resolve_config() -> EGRASConfig:
    """Load the e-GRAS configuration from Django settings, cached."""

    def get(name, default):
        return getattr(settings, name, default)

    return EGRASConfig(
        payment_url=get("EGRAS_PAYMENT_URL", ""),
        verify_url=get("EGRAS_VERIFY_URL", ""),
        return_url=get("EGRAS_RETURN_URL", ""),
        dept_code=get("EGRAS_DEPT_CODE", ""),
        dto=get("EGRAS_DTO", ""),
        sto=get("EGRAS_STO", ""),
        ddo=get("EGRAS_DDO", ""),
        office_name=get("EGRAS_OFFICE_NAME", ""),
        user_id=get("EGRAS_USER_ID", "") or "guest",
        scheme_map=dict(get("EGRAS_SCHEME_MAP", {}) or {}),
        max_schemes=int(get("EGRAS_MAX_SCHEMES", 4)),
        bank_options=_bank_options(get("EGRAS_BANK_OPTIONS", ())),
        default_bank=get("EGRAS_DEFAULT_BANK", ""),
        application_prefix=get("EGRAS_APPLICATION_PREFIX", "") or "DR",
        remarks_template=get("EGRAS_REMARKS_TEMPLATE", "") or "Dristi {demand_numbers}",
        payer_fallback_city=get("EGRAS_PAYER_FALLBACK_CITY", "") or "NA",
        payer_fallback_address=get("EGRAS_PAYER_FALLBACK_ADDRESS", "") or "NA",
        payer_fallback_pincode=get("EGRAS_PAYER_FALLBACK_PINCODE", "") or "000000",
        timeout=int(get("EGRAS_TIMEOUT", 15)),
        verify_ssl=bool(get("EGRAS_VERIFY_SSL", True)),
        pending_horizon=timedelta(days=int(get("EGRAS_PENDING_HORIZON", 9))),
        not_found_grace=timedelta(hours=int(get("EGRAS_NOT_FOUND_GRACE", 2))),
        enabled=bool(get("EGRAS_ENABLED", True)),
    )


def reset_config_cache() -> None:
    """Clear the cached configuration (needed when overriding settings)."""

    resolve_config.cache_clear()


@receiver(setting_changed)
def _reset_config_cache_on_setting_change(sender, setting, **kwargs):
    """Auto-clear the cache when an ``EGRAS_*`` setting changes (e.g. in tests)."""

    if setting.startswith("EGRAS_"):
        reset_config_cache()


def is_active_provider() -> bool:
    """Whether e-GRAS is a registered payment provider (spec 0022 #9.3).

    When it is not registered the system checks stay silent, so local and CI
    environments need no e-GRAS codes.
    """

    from apps.payments import conf as payments_conf

    return constants.PROVIDER_NAME in payments_conf.providers()
