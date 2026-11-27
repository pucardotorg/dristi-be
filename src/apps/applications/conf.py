"""Configuration read from the store (spec 0033 #16.5).

Read at the point of use, so an admin edit applies to the next request. Keys
spec 0033 lists under ``applications.<STATE_CODE>`` are read from the set
``applications.<state code, lowercased>`` (config set names are lowercase,
``apps.core.models.CONFIG_NAME_PATTERN``), then from ``applications``, then the
default here. Values are coerced here, at the read boundary.
"""

import json
import logging
from decimal import Decimal, InvalidOperation

from apps.core import services as config

logger = logging.getLogger(__name__)

CONFIG_SET = "applications"
WEEKDAY_CODES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

DEFAULT_RESCHEDULE_REASONS = [
    {"code": "PARTY_UNAVAILABLE", "label": "Party or witness cannot attend"},
    {"code": "COUNSEL_ENGAGED", "label": "Counsel engaged in another court"},
    {"code": "ILLNESS", "label": "Illness"},
    {"code": "SETTLEMENT_TALKS", "label": "Settlement being negotiated"},
    {"code": "OTHER", "label": "Other"},
]
DEFAULT_EDIT_LITIGANT = {"raised_by_sides": ["COMPLAINANT", "ACCUSED"], "editable": "OWN_LITIGANTS"}
DEFAULT_SIGNING_METHODS = ("AADHAAR_ESIGN",)


def state_set(state_code):
    return f"{CONFIG_SET}.{state_code.lower()}" if state_code else CONFIG_SET


def _state_raw(state_code, key):
    """The value from the state's set, else the shared set, else None."""
    for config_set in dict.fromkeys((state_set(state_code), CONFIG_SET)):
        value = config.get(config_set, key, None)
        if value is not None:
            return value
    return None


def _json(raw, default, key):
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except ValueError:
        logger.error("event=APPLICATION_CONFIG_INVALID key=%s", key)
        return default


def _bool(raw, default):
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def fee(state_code, type_code) -> Decimal:
    """The fee for a type in a state; ``0`` skips Pending Payment (``ALC-01``)."""
    raw = _state_raw(state_code, f"fee.{type_code.lower()}")
    try:
        amount = Decimal(str(raw)) if raw not in (None, "") else Decimal("0")
        if not amount.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        logger.error("event=APPLICATION_CONFIG_INVALID key=fee.%s", type_code.lower())
        return Decimal("0")
    return max(amount, Decimal("0"))


def numbering(state_code) -> dict:
    """The state's numbering settings (#7); a missing submission format is ``None``."""
    return {
        "submission_number_format": _state_raw(state_code, "submission_number_format") or None,
        "submission_number_scope": (
            _state_raw(state_code, "submission_number_scope") or "CASE"
        ).upper(),
        "submission_number_yearly": _bool(
            _state_raw(state_code, "submission_number_yearly"), False
        ),
        "replace_on_onboarding": _bool(_state_raw(state_code, "replace_on_onboarding"), False),
        "replacement_number_format": _state_raw(state_code, "replacement_number_format") or None,
        "replacement_number_scope": (
            _state_raw(state_code, "replacement_number_scope") or "CASE"
        ).upper(),
        "replacement_number_yearly": _bool(
            _state_raw(state_code, "replacement_number_yearly"), True
        ),
        "numbers_from_cis": _bool(_state_raw(state_code, "numbers_from_cis"), False),
    }


def cis_outcomes(state_code) -> list[dict] | None:
    """The state's CIS outcome list, or None where the question is not asked (``ALC-36``)."""
    value = _json(_state_raw(state_code, "cis_outcomes"), None, "cis_outcomes")
    return value if isinstance(value, list) and value else None


def non_working_weekdays(state_code) -> frozenset[int]:
    """Weekday numbers (Monday = 0) staff do not work (#6.9)."""
    raw = _state_raw(state_code, "non_working_weekdays") or "SUN"
    codes = {code.strip().upper() for code in raw.split(",") if code.strip()}
    return frozenset(WEEKDAY_CODES.index(code) for code in codes if code in WEEKDAY_CODES)


def default_state_code() -> str:
    return config.get(CONFIG_SET, "default_state_code", "") or ""


def edit_litigant_details() -> dict:
    value = _json(
        config.get(CONFIG_SET, "edit_litigant_details", None),
        DEFAULT_EDIT_LITIGANT,
        "edit_litigant_details",
    )
    if not isinstance(value, dict):
        return DEFAULT_EDIT_LITIGANT
    return {**DEFAULT_EDIT_LITIGANT, **value}


def suggested_by_stage() -> dict:
    value = _json(config.get(CONFIG_SET, "suggested_by_stage", None), {}, "suggested_by_stage")
    return value if isinstance(value, dict) else {}


def reschedule_reasons() -> list[dict]:
    value = _json(
        config.get(CONFIG_SET, "reschedule_reasons", None),
        DEFAULT_RESCHEDULE_REASONS,
        "reschedule_reasons",
    )
    return value if isinstance(value, list) else DEFAULT_RESCHEDULE_REASONS


def details_max_bytes() -> int:
    return config.get_int(CONFIG_SET, "details_max_bytes", 65536)


def closed_view_days() -> int:
    return config.get_int(CONFIG_SET, "closed_view_days", 30)


def workflow_max_retries() -> int:
    return config.get_int(CONFIG_SET, "workflow_max_retries", 3)


def expiry_batch_size() -> int:
    return config.get_int(CONFIG_SET, "expiry_batch_size", 500)


def signing_methods() -> tuple[str, ...]:
    """The enabled signing methods, shared with orders (``SGM-05``)."""
    raw = config.get("signing", "methods", None)
    if not raw:
        return DEFAULT_SIGNING_METHODS
    return tuple(code.strip().upper() for code in raw.split(",") if code.strip())
