"""Recipient filtering: kill-switch, default-number override, allow/deny lists."""

import logging
import re
from functools import lru_cache

from apps.messaging.services import RecipientFilteredError

from . import constants

logger = logging.getLogger(constants.LOGGER_NAME)


@lru_cache(maxsize=256)
def compile_pattern(pattern: str) -> re.Pattern:
    """Compile a recipient pattern into an anchored regular expression.

    ``X`` matches any single digit, ``*`` matches any remaining sequence of
    digits, and every other character matches literally. Cached so each
    distinct pattern is compiled once instead of on every message.
    """

    parts = []
    for character in pattern.strip():
        if character == "X":
            parts.append(r"\d")
        elif character == "*":
            parts.append(r"\d*")
        else:
            parts.append(re.escape(character))
    return re.compile("".join(parts))


def matches_any(number: str, patterns) -> bool:
    """Return True when the number fully matches at least one pattern."""

    return any(compile_pattern(pattern).fullmatch(number) for pattern in patterns if pattern)


def resolve_recipient(phone_number: str, cfg, log_context: dict | None = None) -> str:
    """Return the number to send to, or raise when policy suppresses it.

    Matching happens after any default-number override and before the mobile
    prefix is applied.
    """

    context = log_context or {}

    if not cfg.enabled:
        _log_filtered(constants.REASON_DISABLED, context)
        raise RecipientFilteredError(
            "CDAC SMS gateway is disabled", reason=constants.REASON_DISABLED
        )

    number = cfg.default_number if cfg.use_default_number else phone_number

    if cfg.whitelist_numbers and not matches_any(number, cfg.whitelist_numbers):
        _log_filtered(constants.REASON_WHITELIST, context)
        raise RecipientFilteredError(
            "Recipient is not whitelisted", reason=constants.REASON_WHITELIST
        )

    if cfg.blacklist_numbers and matches_any(number, cfg.blacklist_numbers):
        _log_filtered(constants.REASON_BLACKLIST, context)
        raise RecipientFilteredError("Recipient is blacklisted", reason=constants.REASON_BLACKLIST)

    return number


def _log_filtered(reason: str, context: dict) -> None:
    """Emit the FILTERED event."""

    logger.info(
        "event=%s message_id=%s correlation_id=%s gateway=%s reason=%s",
        constants.EVENT_FILTERED,
        context.get("message_id", ""),
        context.get("correlation_id", ""),
        constants.PROVIDER_NAME,
        reason,
    )
