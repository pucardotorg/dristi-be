"""Configuration read from the store, ``config_set = "hearings"`` (spec 0023 #11.9).

Read at the point of use, so an admin edit applies to the next request.
"""

import datetime

from django.conf import settings

from apps.core import services as config

CONFIG_SET = "hearings"
CAPACITY_WARN = "warn"
CAPACITY_BLOCK = "block"
WEEKDAY_CODES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def is_production():
    """Whether the process runs on the production settings module."""
    return str(getattr(settings, "SETTINGS_MODULE", "")).endswith("production")


def _int(key, default):
    return config.get_int(CONFIG_SET, key, default)


def max_hearings_per_day():
    return _int("max_hearings_per_day", 40)


def capacity_mode():
    mode = config.get(CONFIG_SET, "capacity_mode", CAPACITY_WARN).strip().lower()
    return CAPACITY_BLOCK if mode == CAPACITY_BLOCK else CAPACITY_WARN


def non_sitting_weekdays():
    """Return the weekday numbers (Monday = 0) the courts never sit on."""
    raw = config.get(CONFIG_SET, "non_sitting_weekdays", "SUN")
    codes = {code.strip().upper() for code in raw.split(",") if code.strip()}
    return frozenset(WEEKDAY_CODES.index(code) for code in codes if code in WEEKDAY_CODES)


def max_days_ahead():
    return _int("max_days_ahead", 365)


def trial_target_days():
    return _int("trial_target_days", 180)


def adjournment_warning_threshold():
    return _int("adjournment_warning_threshold", 2)


def stale_hold_days():
    return _int("stale_hold_days", 7)


def bulk_max_hearings():
    return _int("bulk_max_hearings", 500)


def board_max_hearings():
    return _int("board_max_hearings", 500)


def bulk_preview_minutes():
    return _int("bulk_preview_minutes", 10)


def sitting_time(court_code=None):
    """Return the time parties are told to report at (#9.3)."""
    default = config.get(CONFIG_SET, "default_sitting_time", "11:00")
    if court_code:
        return config.get(CONFIG_SET, f"sitting_time.{court_code}", default)
    return default


def business_date_override():
    """Return the pinned business date, or None. Never honoured in production (#4)."""
    if is_production():
        return None
    raw = config.get(CONFIG_SET, "business_date_override", "").strip()
    if not raw:
        return None
    return datetime.date.fromisoformat(raw)
