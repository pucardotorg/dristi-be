"""Configuration read from the store, ``config_set = "orders"`` and ``"signing"`` (spec 0039 #12.4).

Read at the point of use, so an admin edit applies to the next request.
"""

from apps.core import services as config

CONFIG_SET = "orders"
SIGNING_SET = "signing"
DEFAULT_SIGNING_METHODS = "AADHAAR_ESIGN"


def _int(key, default):
    return config.get_int(CONFIG_SET, key, default)


def text_max_bytes():
    return _int("text_max_bytes", 262144)


def triggered_tab_days():
    return _int("triggered_tab_days", 30)


def bulk_max_orders():
    return _int("bulk_max_orders", 200)


def run_max_retries():
    return _int("run_max_retries", 3)


def live_poll_seconds():
    return _int("live_poll_seconds", 2)


def signing_methods():
    """Return the enabled signing methods (``SGM-05``), e.g. ``{"AADHAAR_ESIGN"}``."""
    raw = config.get(SIGNING_SET, "methods", DEFAULT_SIGNING_METHODS)
    return {name.strip().upper() for name in raw.split(",") if name.strip()}
