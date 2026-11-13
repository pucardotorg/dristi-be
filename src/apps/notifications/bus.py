"""Event bus for live notification fan-out (spec 0031 §4).

The SSE view and the publish actor talk to a bus interface, not a Redis client
directly, so tests run without Redis and a future transport can be swapped in.
``RedisStreamBus`` is production; ``InMemoryNotificationBus`` is tests only.

Redis Streams are a bounded, short-lived replay buffer — never the source of
truth. PostgreSQL owns the full inbox; a client that falls behind the retained
tail recovers through REST.
"""

from __future__ import annotations

import json
import threading
import time
from abc import ABC, abstractmethod
from collections import deque

from django.conf import settings
from django.utils.module_loading import import_string

ZERO_ID = "0-0"


def compare_ids(a: str, b: str) -> int:
    """Order two Redis stream ids by their ``(milliseconds, sequence)`` tuple.

    Returns -1, 0 or 1. Stream ids are ``<milliseconds>-<sequence>``; they must
    be compared numerically, not lexically (``"10-0" > "9-0"``).
    """
    ta = _id_tuple(a)
    tb = _id_tuple(b)
    return (ta > tb) - (ta < tb)


def _id_tuple(value: str) -> tuple[int, int]:
    """Return ``(ms, seq)`` for a stream id; ``(0, 0)`` for an unparsable one."""
    try:
        ms, _, seq = value.partition("-")
        return (int(ms), int(seq or 0))
    except (AttributeError, ValueError):
        return (0, 0)


class BaseNotificationBus(ABC):
    """Interface the SSE view and the publish actor depend on."""

    @abstractmethod
    def ping(self) -> None:
        """Raise if the bus is not reachable."""

    @abstractmethod
    def publish(self, user_id, payload: dict) -> str:
        """Append one event to the user's stream and return the stream entry id."""

    @abstractmethod
    def first_id(self, user_id) -> str | None:
        """Return the oldest retained stream id, or None when the stream is gone."""

    @abstractmethod
    def last_id(self, user_id) -> str:
        """Return the newest stream id, or ``"0-0"`` for a missing/empty stream."""

    @abstractmethod
    def read(self, user_id, after_id: str, block_ms: int) -> list[tuple[str, dict]]:
        """Read events strictly after ``after_id`` (``"0-0"`` for the whole tail)."""


class RedisStreamBus(BaseNotificationBus):
    """Production bus backed by one Redis Stream per user."""

    def __init__(self):
        import redis

        # Bound both connect and read. Without a socket timeout a blocking
        # XREAD on a half-open connection (failover, NAT/LB idle drop, network
        # partition) never returns: the SSE deadline and degraded paths run
        # only between reads, so the thread would be stuck for good. The socket
        # timeout must exceed the XREAD BLOCK interval (the heartbeat) so a
        # healthy blocking read returns first; a startup check enforces that.
        self._client = redis.Redis.from_url(
            settings.NOTIFICATIONS_REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=settings.NOTIFICATIONS_REDIS_SOCKET_CONNECT_TIMEOUT,
            socket_timeout=settings.NOTIFICATIONS_REDIS_SOCKET_TIMEOUT,
            socket_keepalive=True,
        )

    def _key(self, user_id) -> str:
        return f"{settings.NOTIFICATIONS_STREAM_PREFIX}:{user_id}"

    def ping(self) -> None:
        """Raise ``redis.RedisError`` if Redis is unreachable."""
        self._client.ping()

    def publish(self, user_id, payload: dict) -> str:
        """``XADD`` the payload with an approximate cap, then refresh the TTL."""
        key = self._key(user_id)
        entry_id = self._client.xadd(
            key,
            {"data": json.dumps(payload, separators=(",", ":"))},
            maxlen=settings.NOTIFICATIONS_STREAM_MAXLEN,
            approximate=True,
        )
        self._client.expire(key, settings.NOTIFICATIONS_STREAM_TTL_SECONDS)
        return entry_id

    def first_id(self, user_id):
        """Return the oldest retained id, or ``None`` when the stream is gone."""
        entries = self._client.xrange(self._key(user_id), count=1)
        return entries[0][0] if entries else None

    def last_id(self, user_id) -> str:
        """Return the newest id, or ``"0-0"`` for a missing/empty stream."""
        entries = self._client.xrevrange(self._key(user_id), count=1)
        return entries[0][0] if entries else ZERO_ID

    def read(self, user_id, after_id: str, block_ms: int) -> list[tuple[str, dict]]:
        """Block up to ``block_ms`` for entries strictly after ``after_id``."""
        result = self._client.xread(
            {self._key(user_id): after_id or ZERO_ID},
            count=settings.NOTIFICATIONS_SSE_READ_COUNT,
            block=block_ms,
        )
        if not result:
            return []
        _key, entries = result[0]
        return [(entry_id, _decode(fields)) for entry_id, fields in entries]


def _decode(fields: dict) -> dict:
    """Decode the ``data`` field of a stream entry back into a payload dict."""
    raw = fields.get("data")
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


class InMemoryNotificationBus(BaseNotificationBus):
    """Process-local bus for tests. Never configured in production.

    Mirrors the Redis contract closely enough for the SSE and actor tests:
    bounded per-user history, monotonically increasing ids, a blocking read
    that wakes on publish, and first/last id semantics.
    """

    def __init__(self):
        self._streams: dict[str, deque] = {}
        self._seq = 0
        self._lock = threading.Lock()
        self._event = threading.Condition(self._lock)

    def _maxlen(self) -> int:
        return settings.NOTIFICATIONS_STREAM_MAXLEN

    def ping(self) -> None:
        """Always reachable."""

    def _next_id(self) -> str:
        self._seq += 1
        return f"{int(time.time() * 1000)}-{self._seq}"

    def publish(self, user_id, payload: dict) -> str:
        key = str(user_id)
        with self._event:
            stream = self._streams.setdefault(key, deque(maxlen=self._maxlen()))
            entry_id = self._next_id()
            stream.append((entry_id, dict(payload)))
            self._event.notify_all()
            return entry_id

    def first_id(self, user_id):
        stream = self._streams.get(str(user_id))
        return stream[0][0] if stream else None

    def last_id(self, user_id) -> str:
        stream = self._streams.get(str(user_id))
        return stream[-1][0] if stream else ZERO_ID

    def read(self, user_id, after_id: str, block_ms: int) -> list[tuple[str, dict]]:
        key = str(user_id)
        deadline = time.monotonic() + (block_ms / 1000.0)
        with self._event:
            while True:
                entries = self._after(key, after_id or ZERO_ID)
                if entries:
                    return entries
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._event.wait(timeout=remaining)

    def _after(self, key: str, after_id: str) -> list[tuple[str, dict]]:
        stream = self._streams.get(key)
        if not stream:
            return []
        return [
            (entry_id, dict(payload))
            for entry_id, payload in stream
            if compare_ids(entry_id, after_id) > 0
        ]


_bus_cache: dict[str, BaseNotificationBus] = {}


def get_bus() -> BaseNotificationBus:
    """Return the cached bus instance named by ``settings.NOTIFICATIONS_EVENT_BUS``."""
    path = settings.NOTIFICATIONS_EVENT_BUS
    if path not in _bus_cache:
        _bus_cache[path] = import_string(path)()
    return _bus_cache[path]


def clear_bus_cache() -> None:
    """Reset the bus cache (for tests that override the setting)."""
    _bus_cache.clear()
