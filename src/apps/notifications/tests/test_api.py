"""REST inbox and SSE endpoint tests (spec 0031 §11.5).

Error tests assert the code and field, never the message (spec 0000 §13).
"""

import json
import threading
import time

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.api import errors as api_errors
from apps.notifications import services
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

LIST = reverse("notification-list")
READ_ALL = reverse("notification-read-all")
UNREAD_COUNT = reverse("notification-unread-count")
SUBSCRIBE = reverse("notification-subscribe")


def detail_url(notification_id):
    return reverse("notification-detail", kwargs={"id": notification_id})


def read_url(notification_id):
    return reverse("notification-read", kwargs={"id": notification_id})


def error_codes(response):
    """Return ``{field: [code, ...]}`` for a standard error body.

    Parses the raw content, not ``response.json()``: the subscribe endpoint
    renders its pre-stream error body through ``EventStreamRenderer``, so the
    JSON arrives with a ``text/event-stream`` content type.
    """
    body = json.loads(response.content)
    codes = {}
    for error in body["errors"]:
        codes.setdefault(error.get("field"), []).append(error["code"])
    return codes


def make_notification(user, **overrides):
    fields = {"recipient": user, "event_type": "CASE_FILED", "title": "t"}
    fields.update(overrides)
    return Notification.objects.create(**fields)


# ---------------------------------------------------------------------------
# Authentication / gating
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method,url_name",
    [
        ("get", "notification-list"),
        ("get", "notification-unread-count"),
        ("post", "notification-read-all"),
        ("get", "notification-subscribe"),
    ],
)
def test_endpoints_require_authentication(method, url_name):
    url = reverse(url_name)
    response = getattr(APIClient(), method)(url)
    # SessionAuthentication sets no WWW-Authenticate header, so DRF reports a
    # missing credential as 403 (not 401), with the E00102 code.
    assert response.status_code == 403
    assert error_codes(response)[None] == [api_errors.NOT_AUTHENTICATED.code]


# ---------------------------------------------------------------------------
# List and retrieve
# ---------------------------------------------------------------------------


def test_list_returns_only_callers_rows_newest_first(client, user, other_user):
    make_notification(user, title="first")
    make_notification(user, title="second")
    make_notification(other_user, title="theirs")

    response = client.get(LIST)
    assert response.status_code == 200
    body = response.json()
    assert "meta" in body
    titles = [row["title"] for row in body["results"]]
    assert titles == ["second", "first"]


def test_unfiltered_list_includes_read_rows(client, user):
    """Regression: an unfiltered list must not silently drop read rows.

    A missing ``is_read`` query param must not be coerced to ``False`` (the
    QueryDict/BooleanField HTML-form default), which would return unread only.
    """
    unread = make_notification(user, title="unread")
    read = make_notification(user, title="read")
    services.mark_read(read, actor=user)

    response = client.get(LIST)
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert ids == {str(unread.id), str(read.id)}


def test_retrieve_serializer_fields_and_no_recipient(client, user):
    notification = make_notification(user, body="b", data={"k": "v"})
    response = client.get(detail_url(notification.id))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "event_type",
        "title",
        "body",
        "data",
        "priority",
        "is_read",
        "read_at",
        "created_at",
        "meta",
    }
    assert "recipient" not in body


def test_retrieve_other_users_row_is_404(client, other_user):
    notification = make_notification(other_user)
    response = client.get(detail_url(notification.id))
    assert response.status_code == 404
    assert error_codes(response)[None] == [api_errors.NOT_FOUND.code]


def test_list_is_read_filter(client, user):
    unread = make_notification(user, title="unread")
    read = make_notification(user, title="read")
    services.mark_read(read, actor=user)

    response = client.get(LIST, {"is_read": "true"})
    assert [r["id"] for r in response.json()["results"]] == [str(read.id)]
    response = client.get(LIST, {"is_read": "false"})
    assert [r["id"] for r in response.json()["results"]] == [str(unread.id)]


def test_list_event_type_and_priority_filters(client, user):
    a = make_notification(user, event_type="CASE_FILED", priority="HIGH")
    make_notification(user, event_type="HEARING_SCHEDULED", priority="LOW")

    response = client.get(LIST, {"event_type": "CASE_FILED"})
    assert [r["id"] for r in response.json()["results"]] == [str(a.id)]
    response = client.get(LIST, {"priority": "HIGH"})
    assert [r["id"] for r in response.json()["results"]] == [str(a.id)]


def test_list_invalid_is_read_is_400(client):
    response = client.get(LIST, {"is_read": "maybe"})
    assert response.status_code == 400
    assert error_codes(response)["is_read"] == [api_errors.INVALID.code]


def test_list_invalid_priority_is_400(client):
    response = client.get(LIST, {"priority": "URGENT"})
    assert response.status_code == 400
    assert error_codes(response)["priority"] == [api_errors.INVALID_CHOICE.code]


# ---------------------------------------------------------------------------
# Read actions
# ---------------------------------------------------------------------------


def test_mark_read_is_idempotent(client, user):
    notification = make_notification(user)
    first = client.post(read_url(notification.id))
    assert first.status_code == 200
    assert first.json()["is_read"] is True
    second = client.post(read_url(notification.id))
    assert second.status_code == 200
    assert second.json()["read_at"] == first.json()["read_at"]


def test_mark_read_other_users_row_is_404(client, other_user):
    notification = make_notification(other_user)
    response = client.post(read_url(notification.id))
    assert response.status_code == 404
    assert error_codes(response)[None] == [api_errors.NOT_FOUND.code]


def test_read_all_returns_count_and_is_idempotent(client, user):
    make_notification(user)
    make_notification(user)
    first = client.post(READ_ALL)
    assert first.status_code == 200
    assert first.json()["updated"] == 2
    second = client.post(READ_ALL)
    assert second.json()["updated"] == 0


def test_unread_count(client, user):
    make_notification(user)
    make_notification(user)
    read = make_notification(user)
    services.mark_read(read, actor=user)
    response = client.get(UNREAD_COUNT)
    assert response.status_code == 200
    assert response.json()["count"] == 2


def test_no_create_endpoint(client):
    response = client.post(LIST, {"event_type": "X", "title": "t"}, format="json")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# SSE subscribe
# ---------------------------------------------------------------------------


def _consume(response, limit=12):
    """Read up to ``limit`` chunks from a streaming response, then stop."""
    chunks = []
    for chunk in response.streaming_content:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        if len(chunks) >= limit:
            break
    response.close()
    return "".join(chunks)


def test_subscribe_headers_and_connected(client, user, settings):
    settings.NOTIFICATIONS_SSE_MAX_DURATION_SECONDS = 1
    settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = 1
    response = client.get(SUBSCRIBE)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream; charset=utf-8"
    assert response["Cache-Control"] == "no-cache, no-store"
    assert response["X-Accel-Buffering"] == "no"

    body = _consume(response, limit=2)
    assert "retry: " in body
    assert "event: connected" in body
    assert str(user.id) in body


def test_subscribe_accepts_event_stream_accept_header(client, settings):
    """Accept: text/event-stream must negotiate (no 406 E00107)."""
    settings.NOTIFICATIONS_SSE_MAX_DURATION_SECONDS = 1
    settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = 1
    response = client.get(SUBSCRIBE, HTTP_ACCEPT="text/event-stream")
    assert response.status_code == 200


def test_subscribe_unauthenticated_with_event_stream_accept_is_json_error():
    response = APIClient().get(SUBSCRIBE, HTTP_ACCEPT="text/event-stream")
    assert response.status_code == 403
    assert error_codes(response)[None] == [api_errors.NOT_AUTHENTICATED.code]


def test_subscribe_delivers_published_notification(client, user, bus, settings):
    settings.NOTIFICATIONS_SSE_MAX_DURATION_SECONDS = 3
    settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = 2
    # Publish shortly after the stream opens (and after its connect-time cursor
    # is fixed at the empty stream) so the entry is delivered live.
    published = {}

    def publish_soon():
        time.sleep(0.2)
        published["id"] = bus.publish(user.id, {"id": "abc", "event_type": "CASE_FILED"})

    timer = threading.Thread(target=publish_soon)
    timer.start()

    response = client.get(SUBSCRIBE)
    body = ""
    for chunk in response.streaming_content:
        body += chunk.decode()
        if "event: notification" in body:
            break
    response.close()
    timer.join()

    assert "event: notification" in body
    assert f"id: {published['id']}" in body
    assert '"event_type":"CASE_FILED"' in body


def test_subscribe_resyncs_on_trimmed_cursor(client, user, bus, settings):
    settings.NOTIFICATIONS_SSE_MAX_DURATION_SECONDS = 1
    settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = 1
    # Stream has entries, but the client's cursor predates the oldest retained.
    bus.publish(user.id, {"id": "a"})
    response = client.get(SUBSCRIBE, HTTP_LAST_EVENT_ID="1-0")
    body = _consume(response, limit=3)
    assert "event: resync" in body
    assert '"reason":"tail_lost"' in body


def test_subscribe_missing_stream_with_cursor_resyncs(client, settings):
    settings.NOTIFICATIONS_SSE_MAX_DURATION_SECONDS = 1
    settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = 1
    response = client.get(SUBSCRIBE, HTTP_LAST_EVENT_ID="1-0")
    body = _consume(response, limit=3)
    assert "event: resync" in body


def test_subscribe_invalid_cursor_starts_live_without_resync(client, user, bus, settings):
    settings.NOTIFICATIONS_SSE_MAX_DURATION_SECONDS = 1
    settings.NOTIFICATIONS_SSE_HEARTBEAT_SECONDS = 1
    bus.publish(user.id, {"id": "a"})
    response = client.get(SUBSCRIBE, HTTP_LAST_EVENT_ID="not-a-valid-id")
    body = _consume(response, limit=3)
    assert "event: connected" in body
    assert "event: resync" not in body
