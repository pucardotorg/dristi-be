"""Response metadata helpers for API payloads."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

SPEC_VERSION = "1.0"
IST_TIMEZONE = ZoneInfo("Asia/Kolkata")


def build_response_meta() -> dict[str, str]:
    """Return standard response metadata for API payloads."""

    timestamp = timezone.now().astimezone(IST_TIMEZONE).isoformat()
    return {
        "timestamp": timestamp,
        "app_version": getattr(settings, "GIT_COMMIT_SHA", "unknown"),
        "spec_version": SPEC_VERSION,
    }
