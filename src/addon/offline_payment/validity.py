"""Validity window of a payment request (spec 0032 #6.1).

::

    issued_on   = the YYMMDD date in the reference (IST)
    valid_until = issued_on + validity days, at 23:59:59.999999 IST
    expires_at  = valid_until + recording grace

The validity is read from configuration when checked, not frozen into the
reference: lengthening it extends requests already issued, shortening it can
expire them early. Both are deliberate operator decisions.
"""

from datetime import date, datetime, time

from .config import OfflineConfig
from .constants import IST


def valid_until(issued_on: date, config: OfflineConfig) -> datetime:
    """The last moment the payer may pay (the money must be collected by then)."""

    last_day = issued_on + config.validity
    return datetime.combine(last_day, time.max, tzinfo=IST)


def expires_at(issued_on: date, config: OfflineConfig) -> datetime:
    """The last moment staff may record a collection made in time."""

    return valid_until(issued_on, config) + config.grace


def is_expired(issued_on: date, config: OfflineConfig, now: datetime) -> bool:
    """Whether the request can no longer be recorded at ``now``."""

    return now > expires_at(issued_on, config)


def ist_date(moment: datetime) -> date:
    """The IST calendar date of ``moment``."""

    return moment.astimezone(IST).date()


def format_ist(moment: datetime) -> str:
    """``18 Nov 2026, 11:59 PM IST`` — how a deadline is shown to the payer."""

    local = moment.astimezone(IST)
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"{local.day} {local.strftime('%b %Y')}, {hour}:{local.strftime('%M %p')} IST"
