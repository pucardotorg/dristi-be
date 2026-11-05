"""Startup validation of the cases settings."""

from django.conf import settings
from django.core.checks import Error, register

from .services import DRAFT_CACHE_ALIAS

DUMMY_CACHE = "django.core.cache.backends.dummy.DummyCache"


@register()
def check_draft_cache(app_configs, **kwargs):
    """Refuse a missing or dummy draft-session cache.

    A draft exists only in this cache until its first save. With a dummy
    backend ``POST /cases`` would still return a draft id, and every save on
    it would then fail with 404 and nothing to say why.
    """
    backend = settings.CACHES.get(DRAFT_CACHE_ALIAS, {}).get("BACKEND")
    if backend is None:
        return [
            Error(
                f"CACHES has no {DRAFT_CACHE_ALIAS!r} alias for case draft sessions.",
                hint="Set STATE_CACHE_REDIS_URL.",
                id="cases.E001",
            )
        ]
    if backend == DUMMY_CACHE:
        return [
            Error(
                f"CACHES[{DRAFT_CACHE_ALIAS!r}] is a dummy cache; case draft sessions would be lost.",
                hint="Point STATE_CACHE_REDIS_URL at a Redis database.",
                id="cases.E002",
            )
        ]
    return []
