"""Offline payment configuration loading (spec 0032 #13).

Flat ``OFFLINE_PAYMENT_*`` settings are read into a frozen, cached
:class:`OfflineConfig`. Loading never fails: a malformed value is kept as it
was given (or recorded as a problem) so that ``validate()`` — run by the system
checks — can report it, rather than crashing at import. There are no
credentials. The cache is cleared automatically when an ``OFFLINE_PAYMENT_*``
setting changes, as ``EGRASConfig`` does.
"""

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver

from . import constants

PREFIX_RE = re.compile(r"^[A-Z]{2,4}$")


@dataclass(frozen=True)
class Counter:
    """One place where money is accepted (spec 0032 #5.3)."""

    code: str
    label: str
    address: str = ""
    hours: str = ""


@dataclass(frozen=True)
class OfflineConfig:
    """Immutable snapshot of the offline payment configuration."""

    enabled: bool = True
    label: str = constants.DEFAULT_LABEL
    reference_prefix: str = constants.DEFAULT_PREFIX
    # Kept as given: a non-integer is reported by validate() and replaced by
    # the default wherever a value is needed.
    validity_days: object = constants.DEFAULT_VALIDITY_DAYS
    grace_hours: object = constants.DEFAULT_GRACE_HOURS
    methods: tuple[str, ...] = constants.DEFAULT_METHODS
    counters: tuple[Counter, ...] = ()
    counters_problem: str = ""
    default_counter: str = ""
    instructions: str = constants.DEFAULT_INSTRUCTIONS
    payable_to: str = ""
    max_amount_raw: str = ""
    cash_max_amount_raw: str = ""
    allowed_charge_types: tuple[str, ...] = ()
    receipt_pattern: str = constants.DEFAULT_RECEIPT_PATTERN
    dd_max_age_days: object = constants.DEFAULT_DD_MAX_AGE_DAYS

    # -- derived values -----------------------------------------------------
    @property
    def validity(self) -> timedelta:
        """How many days after the issue date a request may be paid."""

        return timedelta(days=_int_or(self.validity_days, constants.DEFAULT_VALIDITY_DAYS))

    @property
    def grace(self) -> timedelta:
        """How long after ``valid_until`` a collection may still be recorded."""

        return timedelta(hours=_int_or(self.grace_hours, constants.DEFAULT_GRACE_HOURS))

    @property
    def pending_horizon(self) -> timedelta:
        """Validity + grace + one day (spec 0032 #6.3).

        A request is issued on a day and valid to the end of the
        ``validity``-th day after it, so it can never be open for longer than
        ``validity + 1 day + grace``; the poller reaches ``FAILED`` first.
        """

        return self.validity + self.grace + timedelta(days=1)

    @property
    def dd_max_age(self) -> timedelta:
        """Oldest demand draft accepted, relative to the collection date."""

        return timedelta(days=_int_or(self.dd_max_age_days, constants.DEFAULT_DD_MAX_AGE_DAYS))

    @property
    def max_amount(self) -> Decimal | None:
        """Largest request offered offline, or ``None`` for no cap."""

        return _amount(self.max_amount_raw)

    @property
    def cash_max_amount(self) -> Decimal | None:
        """Largest amount accepted in cash, or ``None`` for no cap."""

        return _amount(self.cash_max_amount_raw)

    @property
    def receipt_re(self) -> re.Pattern | None:
        """The compiled receipt pattern, or ``None`` when it does not compile."""

        return _compile(self.receipt_pattern)

    def counter(self, code: str) -> Counter | None:
        """The counter called ``code``, if configured."""

        return next((counter for counter in self.counters if counter.code == code), None)

    # -- validation (spec 0032 #13.3) ---------------------------------------
    def validate(self) -> list[tuple[str, str]]:
        """Return ``(check_id, message)`` for every configuration problem."""

        from apps.payments.enums import ChargeType

        from . import methods

        problems = []
        if not PREFIX_RE.match(self.reference_prefix or ""):
            problems.append(
                ("E001", "OFFLINE_PAYMENT_REFERENCE_PREFIX must be 2-4 upper-case letters.")
            )

        validity = _int(self.validity_days)
        if validity is None or not (
            constants.MIN_VALIDITY_DAYS <= validity <= constants.MAX_VALIDITY_DAYS
        ):
            problems.append(("E002", "OFFLINE_PAYMENT_VALIDITY_DAYS must be an integer 1-90."))
        grace = _int(self.grace_hours)
        if grace is None or not (constants.MIN_GRACE_HOURS <= grace <= constants.MAX_GRACE_HOURS):
            problems.append(
                ("E002", "OFFLINE_PAYMENT_RECORDING_GRACE_HOURS must be an integer 0-168.")
            )

        if not self.methods:
            problems.append(("E003", "OFFLINE_PAYMENT_METHODS must name at least one method."))
        unknown = [code for code in self.methods if code not in methods.SUPPORTED]
        if unknown:
            problems.append(
                (
                    "E003",
                    f"OFFLINE_PAYMENT_METHODS names unsupported methods {unknown}; "
                    f"supported: {list(methods.SUPPORTED)}.",
                )
            )
        if len(set(self.methods)) != len(self.methods):
            problems.append(("E003", "OFFLINE_PAYMENT_METHODS lists a method more than once."))

        problems.extend(("E004", message) for message in self._counter_problems())

        if constants.DEMAND_DRAFT in self.methods and not self.payable_to.strip():
            problems.append(
                (
                    "E005",
                    "OFFLINE_PAYMENT_PAYABLE_TO is required when DEMAND_DRAFT is an accepted "
                    "method.",
                )
            )

        for setting_name, raw in (
            ("OFFLINE_PAYMENT_MAX_AMOUNT", self.max_amount_raw),
            ("OFFLINE_PAYMENT_CASH_MAX_AMOUNT", self.cash_max_amount_raw),
        ):
            if str(raw).strip() and _amount(raw) is None:
                problems.append(
                    (
                        "E006",
                        f"{setting_name} must be a positive amount with at most two decimals.",
                    )
                )

        valid_charges = set(ChargeType.values)
        bad_charges = [value for value in self.allowed_charge_types if value not in valid_charges]
        if bad_charges:
            problems.append(
                (
                    "E007",
                    f"OFFLINE_PAYMENT_ALLOWED_CHARGE_TYPES names unknown charge types {bad_charges}.",
                )
            )

        if self.receipt_re is None:
            problems.append(("E008", "OFFLINE_PAYMENT_RECEIPT_PATTERN is not a valid regex."))

        dd_age = _int(self.dd_max_age_days)
        if dd_age is None or dd_age < 1:
            problems.append(("E009", "OFFLINE_PAYMENT_DD_MAX_AGE_DAYS must be an integer >= 1."))

        if len(self.instructions or "") > constants.INSTRUCTIONS_MAX_LENGTH:
            # Reported with the counters: both are payer-facing text.
            problems.append(
                ("E004", "OFFLINE_PAYMENT_INSTRUCTIONS must be at most 500 characters.")
            )
        return problems

    def _counter_problems(self):
        if self.counters_problem:
            yield self.counters_problem
            return
        codes = [counter.code for counter in self.counters]
        if any(not code.strip() for code in codes):
            yield "Every OFFLINE_PAYMENT_COUNTERS entry needs a non-empty code."
        if len(set(codes)) != len(codes):
            yield "OFFLINE_PAYMENT_COUNTERS codes must be unique."
        if any(not counter.label.strip() for counter in self.counters):
            yield "Every OFFLINE_PAYMENT_COUNTERS entry needs a non-empty label."
        if self.default_counter and self.default_counter not in codes:
            yield "OFFLINE_PAYMENT_DEFAULT_COUNTER must be one of the OFFLINE_PAYMENT_COUNTERS codes."


def _int(value) -> int | None:
    """``value`` as an int, or ``None`` when it is not a whole number."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _int_or(value, default: int) -> int:
    parsed = _int(value)
    return default if parsed is None else parsed


def _amount(raw) -> Decimal | None:
    """A positive amount with at most two decimals, or ``None``."""

    text = str(raw if raw is not None else "").strip()
    if not text:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0 or value != value.quantize(Decimal("0.01")):
        return None
    return value


@lru_cache(maxsize=8)
def _compile(pattern: str) -> re.Pattern | None:
    try:
        return re.compile(pattern)
    except (re.error, TypeError):
        return None


def _as_list(raw) -> tuple[str, ...]:
    """A list setting given as a list or a comma-separated string."""

    if raw is None:
        return ()
    if isinstance(raw, str):
        raw = raw.split(",")
    return tuple(str(value).strip() for value in raw if str(value).strip())


def _counters(raw) -> tuple[tuple[Counter, ...], str]:
    """Parse ``OFFLINE_PAYMENT_COUNTERS``; returns the counters and a problem, if any."""

    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else []
        except ValueError:
            return (), "OFFLINE_PAYMENT_COUNTERS is not valid JSON."
    if raw is None:
        return (), ""
    if not isinstance(raw, list | tuple):
        return (), "OFFLINE_PAYMENT_COUNTERS must be a JSON list of objects."
    counters = []
    for entry in raw:
        if isinstance(entry, Counter):
            counters.append(entry)
            continue
        if not isinstance(entry, dict):
            return (), "OFFLINE_PAYMENT_COUNTERS must be a JSON list of objects."
        counters.append(
            Counter(
                code=str(entry.get("code") or "").strip(),
                label=str(entry.get("label") or "").strip(),
                address=str(entry.get("address") or "").strip(),
                hours=str(entry.get("hours") or "").strip(),
            )
        )
    return tuple(counters), ""


@lru_cache(maxsize=1)
def resolve_config() -> OfflineConfig:
    """Load the offline payment configuration from Django settings, cached."""

    def get(name, default):
        return getattr(settings, f"{constants.SETTINGS_PREFIX}{name}", default)

    counters, counters_problem = _counters(get("COUNTERS", []))
    methods = get("METHODS", None)
    return OfflineConfig(
        enabled=bool(get("ENABLED", True)),
        label=str(get("LABEL", "") or constants.DEFAULT_LABEL),
        # Kept exactly as configured: a lower-case or padded prefix is reported
        # by E001 rather than silently changing every issued reference.
        reference_prefix=str(get("REFERENCE_PREFIX", "") or constants.DEFAULT_PREFIX),
        validity_days=get("VALIDITY_DAYS", constants.DEFAULT_VALIDITY_DAYS),
        grace_hours=get("RECORDING_GRACE_HOURS", constants.DEFAULT_GRACE_HOURS),
        methods=constants.DEFAULT_METHODS
        if methods is None
        else tuple(code.upper() for code in _as_list(methods)),
        counters=counters,
        counters_problem=counters_problem,
        default_counter=str(get("DEFAULT_COUNTER", "") or "").strip(),
        instructions=str(get("INSTRUCTIONS", constants.DEFAULT_INSTRUCTIONS) or ""),
        payable_to=str(get("PAYABLE_TO", "") or "").strip(),
        max_amount_raw=str(get("MAX_AMOUNT", "") or "").strip(),
        cash_max_amount_raw=str(get("CASH_MAX_AMOUNT", "") or "").strip(),
        allowed_charge_types=_as_list(get("ALLOWED_CHARGE_TYPES", [])),
        receipt_pattern=str(
            get("RECEIPT_PATTERN", constants.DEFAULT_RECEIPT_PATTERN)
            or constants.DEFAULT_RECEIPT_PATTERN
        ),
        dd_max_age_days=get("DD_MAX_AGE_DAYS", constants.DEFAULT_DD_MAX_AGE_DAYS),
    )


def reset_config_cache() -> None:
    """Clear the cached configuration (needed when overriding settings)."""

    resolve_config.cache_clear()


@receiver(setting_changed)
def _reset_config_cache_on_setting_change(sender, setting, **kwargs):
    """Auto-clear the cache when an ``OFFLINE_PAYMENT_*`` setting changes (e.g. in tests)."""

    if setting.startswith(constants.SETTINGS_PREFIX):
        reset_config_cache()


def is_registered() -> bool:
    """Whether the offline provider is a registered payment provider (spec 0032 #13.3)."""

    from apps.payments import conf as payments_conf

    return constants.PROVIDER_NAME in payments_conf.providers()
