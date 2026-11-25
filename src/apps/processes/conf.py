"""Configuration read from the store (spec 0028 #12.3).

Read at the point of use, so an admin edit applies to the next request.
"""

import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from apps.core import services as config

CONFIG_SET = "processes"
# Court dates are Indian dates; the project clock is UTC.
IST = ZoneInfo("Asia/Kolkata")


def court_date(moment=None) -> datetime.date:
    """The date in India at ``moment``, by default now."""
    return (moment or timezone.now()).astimezone(IST).date()


def start_of(day) -> datetime.datetime:
    """00:00 IST on ``day``."""
    return datetime.datetime.combine(day, datetime.time.min, tzinfo=IST)


def state_code() -> str:
    """The deployment's state, e.g. ``KL``: its fees and reason list are read for it."""
    return config.get("tenant", "state_code").strip().upper()


def court_fee(process_type_code) -> Decimal:
    """The flat court fee for a process of this type in this state (``FEE-01``).

    A type with no entry costs nothing: ``payment-logic.md`` §4 lists only
    the types that carry a fee.
    """
    config_set, key = f"{CONFIG_SET}.{state_code()}", f"court_fee.{process_type_code}"
    try:
        fee = Decimal(config.get(config_set, key, "0"))
    except InvalidOperation:
        fee = None
    if fee is None or fee < 0:
        raise ImproperlyConfigured(f"{config_set}.{key} is not an amount of zero or more.")
    return fee


def expiry_batch_size() -> int:
    return config.get_int(CONFIG_SET, "expiry_batch_size", 500)


def bulk_max() -> int:
    return config.get_int(CONFIG_SET, "bulk_max", 200)
