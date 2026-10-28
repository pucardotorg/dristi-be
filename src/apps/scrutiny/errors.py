"""Scrutiny and registration error codes (domain 09, spec 0000 section 9, spec 0024 #8.5)."""

from apps.api.errors import define

# Advisory checks (#2.4). Logged, never returned: a failure degrades the detail
# to one CHECKS_UNAVAILABLE alert instead of blocking the screen.
CHECKS_NOT_BOUND = define(
    "E09014", "No active checks rule is bound for this court establishment.", status=500
)
CHECKS_EVALUATION_FAILED = define(
    "E09015", "The checks rule failed or broke its contract.", status=500
)
