"""Pincode lookup against the India Post Pincode API (spec 0020 §7.3).

The lookup only suggests district and state for the person entering an
address. Nothing here is called when an address is saved, so the API being
down never blocks recording one: the caller is told it is unavailable and the
values are entered by hand instead.
"""

import logging
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY = "address:pincode:{pincode}"

USER_AGENT = "dristi-be"


class PincodeNotFoundError(Exception):
    """India Post answered, and it has no record of the pincode."""


class PincodeServiceUnavailableError(Exception):
    """India Post could not be reached or gave an answer we cannot use."""


@dataclass(frozen=True)
class PincodeDetails:
    """District and state for a pincode."""

    pincode: str
    district: str
    state: str


def lookup_pincode(pincode):
    """Return the :class:`PincodeDetails` for a valid 6-digit ``pincode``.

    Successful answers are cached, since a pincode's district and state
    practically never change; failures are not, so a recovered API is used
    on the next call.

    Raises:
        PincodeNotFoundError: India Post has no record of the pincode.
        PincodeServiceUnavailableError: the API timed out, was unreachable,
            returned a non-200 status, or returned a body we cannot parse.
    """
    key = CACHE_KEY.format(pincode=pincode)
    cached = cache.get(key)
    if cached is not None:
        return PincodeDetails(**cached)

    details = _fetch(pincode)
    cache.set(key, details.__dict__, settings.PINCODE_API_CACHE_SECONDS)
    return details


def _fetch(pincode):
    """Call India Post and turn its answer into details or an error."""
    url = settings.PINCODE_API_URL.format(pincode=pincode)
    try:
        response = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=settings.PINCODE_API_TIMEOUT
        )
    except requests.RequestException as exc:
        logger.warning("Pincode API request failed for %s: %s", pincode, exc)
        raise PincodeServiceUnavailableError from exc

    if response.status_code != 200:
        logger.warning("Pincode API returned HTTP %s for %s", response.status_code, pincode)
        raise PincodeServiceUnavailableError
    try:
        entry = response.json()[0]
        status = entry["Status"]
        offices = entry["PostOffice"]
    except (ValueError, LookupError, TypeError) as exc:
        logger.warning("Pincode API returned an unreadable body for %s", pincode)
        raise PincodeServiceUnavailableError from exc

    if status != "Success" or not offices:
        raise PincodeNotFoundError

    # Every post office under a pincode sits in the same district and state
    # in practice, so the first one answers for all of them.
    try:
        district = offices[0]["District"].strip()
        state = offices[0]["State"].strip()
    except (LookupError, TypeError, AttributeError) as exc:
        logger.warning("Pincode API returned a post office without district/state for %s", pincode)
        raise PincodeServiceUnavailableError from exc

    if not district or not state:
        raise PincodeServiceUnavailableError

    return PincodeDetails(pincode=pincode, district=district, state=state)
