"""Request-language resolution for language-aware endpoints (spec 0030 section 5).

Consumers call :func:`resolve_request_language` and decide themselves what to
do with the result (translation lookup, fallback, ``Content-Language``).
"""

from __future__ import annotations

import re

from apps.api.errors import BusinessError

from . import errors
from .models import Language

LANG_QUERY_PARAM = "lang"

# Headers longer than this are ignored, as Django's own locale handling does,
# so parsing cost stays bounded.
ACCEPT_LANGUAGE_MAX_LENGTH = 500

# One Accept-Language element: a language range and an optional quality value
# (RFC 9110 sections 12.4.2 and 12.5.4). Used with fullmatch().
ACCEPT_LANGUAGE_ITEM_RE = re.compile(
    r"(?P<tag>[A-Za-z]{1,8}(?:-[A-Za-z0-9]{1,8})*|\*)"
    r"(?:\s*;\s*[qQ]\s*=\s*(?P<q>0(?:\.\d{0,3})?|1(?:\.0{0,3})?))?"
)


def resolve_request_language(request) -> Language:
    """Return the language a request asks for.

    The first source that yields an active language wins:

    1. the ``lang`` query parameter, matched case-insensitively; an inactive
       or unknown code raises ``BusinessError(E11001)`` on field ``lang``;
    2. the ``Accept-Language`` header, by descending quality, each tag tried
       exactly and then by its primary subtag (``en-IN`` -> ``en``); unknown
       or malformed tags are skipped;
    3. the default language.
    """
    # Small and cachalot-cached: one read serves every source.
    languages = {language.code: language for language in Language.objects.active()}

    params = getattr(request, "query_params", request.GET)
    if LANG_QUERY_PARAM in params:
        requested = params[LANG_QUERY_PARAM]
        language = languages.get(requested.strip().lower())
        if language is None:
            raise BusinessError(
                errors.LANGUAGE_NOT_SUPPORTED,
                f'Language "{requested}" is not supported.',
                field=LANG_QUERY_PARAM,
            )
        return language

    for tag in parse_accept_language(request.headers.get("Accept-Language", "")):
        language = languages.get(tag) or languages.get(tag.split("-", 1)[0])
        if language is not None:
            return language

    default = next((language for language in languages.values() if language.is_default), None)
    return default or Language.objects.get_default()


def parse_accept_language(header: str) -> list[str]:
    """Return the lowercased language tags of an ``Accept-Language`` header, best first.

    Tags are ordered by descending quality; equal qualities keep header order.
    Malformed elements, the ``*`` wildcard and ``q=0`` ("not acceptable") are
    dropped. An over-long header yields nothing.
    """
    if not header or len(header) > ACCEPT_LANGUAGE_MAX_LENGTH:
        return []

    weighted = []
    for item in header.split(","):
        match = ACCEPT_LANGUAGE_ITEM_RE.fullmatch(item.strip())
        if match is None or match["tag"] == "*":
            continue
        quality = float(match["q"]) if match["q"] else 1.0
        if quality > 0:
            weighted.append((quality, match["tag"].lower()))

    # sorted() is stable, so equal qualities keep their header order.
    return [tag for _, tag in sorted(weighted, key=lambda pair: pair[0], reverse=True)]
