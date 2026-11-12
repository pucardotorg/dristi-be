"""System health checks for /health/ (django-health-check).

The classes keep the library's names so the JSON keys stay the same.
"""

from django.conf import settings
from health_check.contrib.db_heartbeat.backends import DatabaseHeartBeatCheck
from health_check.contrib.redis.backends import RedisHealthCheck as BaseRedisHealthCheck
from health_check.exceptions import ServiceUnavailable
from redis import Redis

# Seconds. Without them redis-py < 8 waits forever on a Redis that accepts
# connections but never replies, holding the worker until it is killed.
REDIS_PROBE_TIMEOUT = 2


class Database(DatabaseHeartBeatCheck):
    """SELECT 1, without the driver's error text in the public response."""

    def check_status(self):
        try:
            super().check_status()
        except ServiceUnavailable as exc:
            # The driver's message names hosts and users. The library logs the
            # chained traceback, so the details stay in the server log.
            raise ServiceUnavailable("Database unavailable.") from exc


class RedisHealthCheck(BaseRedisHealthCheck):
    """Pings the Dramatiq broker's Redis with a client of its own."""

    def __post_init__(self):
        # A client per check: check_status() closes it, and closing a from_url
        # client closes its pool, failing any other check still using it.
        # test.py's stub broker has no url, hence .get().
        self.client = Redis.from_url(
            settings.DRAMATIQ_BROKER["OPTIONS"].get("url", "redis://localhost:6379/2"),
            socket_connect_timeout=REDIS_PROBE_TIMEOUT,
            socket_timeout=REDIS_PROBE_TIMEOUT,
        )
