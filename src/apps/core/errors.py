"""Core API error codes (domain 11, spec 0000 section 9)."""

from apps.api.errors import define

# Languages (spec 0030 #8). Raised with the requested code in the message, on field "lang".
LANGUAGE_NOT_SUPPORTED = define("E11001", "Language is not supported.")
