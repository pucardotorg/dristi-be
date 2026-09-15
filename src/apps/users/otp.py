"""Issue, cooldown and single-use verification of one-time codes (spec 0005).

The OTP is a credential, not input: it is never logged, never returned, and is
destroyed the moment it is used.
"""

import hashlib
import hmac
import logging
import secrets
import time

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

_DIGITS = "0123456789"


class Purpose:
    """What a code was issued for. Part of the cache key, so the two never mix."""

    REGISTER = "register"
    LOGIN = "login"

    CHOICES = (REGISTER, LOGIN)


class ResendTooSoonError(Exception):
    """A code was already sent inside the cooldown window."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"Resend allowed in {retry_after}s.")


def _code_key(purpose: str, mobile_number: str) -> str:
    return f"otp:code:{purpose}:{mobile_number}"


def _cooldown_key(purpose: str, mobile_number: str) -> str:
    return f"otp:cooldown:{purpose}:{mobile_number}"


def _digest(code: str) -> str:
    """Return the keyed digest of a code. The cache never holds the code itself."""
    return hmac.new(
        settings.SECRET_KEY.encode(),
        code.encode(),
        hashlib.sha256,
    ).hexdigest()


def issue_otp(mobile_number: str, purpose: str) -> None:
    """Send a code, or raise `ResendTooSoonError` if one went out inside the cooldown.

    The presence of the cooldown key *is* the cooldown. `cache.add` writes only
    when the key is absent and reports whether it wrote, so the check and the
    claim are one atomic operation and two concurrent taps cannot both send.
    """
    # Read per call, never captured at import, so the dial can be turned without
    # a deploy and tests can override it.
    cooldown = settings.OTP_RESEND_COOLDOWN_SECONDS
    key = _cooldown_key(purpose, mobile_number)
    retry_at = time.time() + cooldown

    if not cache.add(key, retry_at, timeout=cooldown):
        stored_retry_at = cache.get(key) or time.time()
        raise ResendTooSoonError(max(1, int(round(stored_retry_at - time.time()))))

    code = "".join(secrets.choice(_DIGITS) for _ in range(settings.OTP_LENGTH))
    cache.set(
        _code_key(purpose, mobile_number),
        _digest(code),
        timeout=settings.OTP_TTL_SECONDS,
    )
    _send_sms(mobile_number, code)


def verify_and_consume_otp(mobile_number: str, otp: str, purpose: str) -> bool:
    """Return True if `otp` is the outstanding code, destroying it in the process.

    Verification without invalidation permits replay, so the two are one step.
    """
    if not (mobile_number and otp):
        return False

    key = _code_key(purpose, mobile_number)
    stored = cache.get(key)
    if not stored:
        return False

    if not hmac.compare_digest(stored, _digest(str(otp))):
        return False

    # The delete reports whether this caller was the one that removed the key,
    # so a code submitted twice concurrently succeeds at most once.
    return bool(cache.delete(key))


def _send_sms(mobile_number: str, code: str) -> None:
    """Hand the code to the SMS gateway.

    TODO: replace with the real provider, ideally enqueued as a Dramatiq actor so
    a slow gateway cannot hold the request open.
    """
    if settings.DEBUG:
        logger.info("OTP for %s is %s", mobile_number, code)
    else:
        # Never the code itself outside development.
        logger.info("OTP dispatched to %s", mobile_number)
