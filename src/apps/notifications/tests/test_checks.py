"""Startup settings check tests (spec 0031 §9)."""

from apps.notifications.checks import check_notification_settings


def _ids(messages):
    return {m.id for m in messages}


def test_default_settings_pass():
    assert check_notification_settings(None) == []


def test_empty_redis_url(settings):
    settings.NOTIFICATIONS_REDIS_URL = ""
    assert "notifications.E001" in _ids(check_notification_settings(None))


def test_non_redis_scheme(settings):
    settings.NOTIFICATIONS_REDIS_URL = "http://example.com"
    assert "notifications.E002" in _ids(check_notification_settings(None))


def test_empty_stream_prefix(settings):
    settings.NOTIFICATIONS_STREAM_PREFIX = ""
    assert "notifications.E003" in _ids(check_notification_settings(None))


def test_non_positive_int(settings):
    settings.NOTIFICATIONS_STREAM_MAXLEN = 0
    assert "notifications.E004.NOTIFICATIONS_STREAM_MAXLEN" in _ids(
        check_notification_settings(None)
    )


def test_max_duration_not_greater_than_heartbeat(settings):
    settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = 100
    settings.NOTIFICATIONS_SSE_MAX_DURATION_SECONDS = 100
    assert "notifications.E005" in _ids(check_notification_settings(None))


def test_socket_timeout_not_greater_than_heartbeat(settings):
    settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = 20
    settings.NOTIFICATIONS_REDIS_SOCKET_TIMEOUT = 20
    assert "notifications.E006" in _ids(check_notification_settings(None))
