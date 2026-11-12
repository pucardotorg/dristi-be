"""System health checks for /health/ (django-health-check).

The classes keep the library's names so the JSON keys stay the same. Each
check probes with a connection of its own, bounded by PROBE_TIMEOUT, so a
backend that accepts connections but never replies fails the check instead of
holding the worker until Gunicorn kills it. The app's own connections keep
their settings.
"""

import uuid

from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache
from django.db import connections
from django.db.utils import load_backend
from health_check.cache.backends import CacheBackend
from health_check.contrib.db_heartbeat.backends import DatabaseHeartBeatCheck
from health_check.contrib.redis.backends import RedisHealthCheck as BaseRedisHealthCheck
from health_check.exceptions import ServiceUnavailable
from redis import Redis
from redis.exceptions import RedisError

# Seconds. libpq's connect_timeout rounds anything below 2 up to 2.
PROBE_TIMEOUT = 2


class Database(DatabaseHeartBeatCheck):
    """SELECT 1, without the driver's error text in the public response."""

    def check_status(self):
        connection = self._probe_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                if cursor.fetchone() != (1,):
                    raise ServiceUnavailable("Database unavailable.")
        except ServiceUnavailable:
            raise
        except Exception as exc:
            # The driver's message names hosts and users. The library logs the
            # chained traceback, so the details stay in the server log.
            raise ServiceUnavailable("Database unavailable.") from exc
        finally:
            connection.close()

    def _probe_connection(self):
        # A copy: the settings dict is shared with the app's connections.
        settings_dict = {**connections.settings[self.alias]}
        backend = load_backend(settings_dict["ENGINE"])
        if backend.DatabaseWrapper.vendor == "postgresql":
            options = {**settings_dict["OPTIONS"]}
            # A pool here would be a new pool per request.
            options.pop("pool", None)
            options["connect_timeout"] = PROBE_TIMEOUT
            options["options"] = (
                f"{options.get('options', '')} -c statement_timeout={PROBE_TIMEOUT * 1000}"
            ).strip()
            settings_dict["OPTIONS"] = options
        return backend.DatabaseWrapper(settings_dict, self.alias)


class Cache(CacheBackend):
    """Sets and reads back a key, through a cache client with timeouts."""

    def check_status(self):
        cache = self._probe_cache()
        key = f"{self.key_prefix}:{uuid.uuid4().hex}"
        try:
            cache.set(key, "itworks")
            if cache.get(key) != "itworks":
                raise ServiceUnavailable("Cache unavailable.")
            cache.delete(key)
        except (ConnectionError, RedisError, ValueError) as exc:
            raise ServiceUnavailable("Cache unavailable.") from exc
        finally:
            if isinstance(cache, RedisCache):
                # RedisCache has no close(); drop this probe's sockets now.
                for pool in cache._cache._pools.values():
                    pool.disconnect()

    def _probe_cache(self):
        params = {**settings.CACHES[self.alias]}
        backend = params.pop("BACKEND")
        location = params.pop("LOCATION", "")
        if backend != "django.core.cache.backends.redis.RedisCache":
            # Local-memory and dummy caches cannot hang.
            return caches[self.alias]
        params["OPTIONS"] = {
            **params.get("OPTIONS", {}),
            "socket_connect_timeout": PROBE_TIMEOUT,
            "socket_timeout": PROBE_TIMEOUT,
        }
        return RedisCache(location, params)


class RedisHealthCheck(BaseRedisHealthCheck):
    """Pings the Dramatiq broker's Redis with a client of its own."""

    def __post_init__(self):
        # A client per check: check_status() closes it, and closing a from_url
        # client closes its pool, failing any other check still using it.
        # test.py's stub broker has no url, hence .get().
        self.client = Redis.from_url(
            settings.DRAMATIQ_BROKER["OPTIONS"].get("url", "redis://localhost:6379/2"),
            socket_connect_timeout=PROBE_TIMEOUT,
            socket_timeout=PROBE_TIMEOUT,
        )
