"""API app tests."""

import io
import json
from datetime import datetime
from unittest.mock import patch

from django.core.cache import caches
from django.core.cache.backends.redis import RedisCacheClient
from django.core.management import call_command
from django.db import OperationalError, connections
from django.test import override_settings
from django.urls import reverse
from redis import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from rest_framework import status
from rest_framework.test import APITestCase

from apps.api.health import PROBE_TIMEOUT, Cache, Database
from apps.core.models import ApiVersionChangeLog
from apps.users.models import User


class HealthCheckTests(APITestCase):
    """Health endpoint tests."""

    def assert_meta(self, payload):
        """Assert standard response metadata exists and has expected shape."""

        self.assertIn("meta", payload)
        self.assertEqual(payload["meta"]["spec_version"], "1.0")
        self.assertIn("app_version", payload["meta"])
        self.assertIn("timestamp", payload["meta"])
        parsed = datetime.fromisoformat(payload["meta"]["timestamp"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(payload["meta"]["timestamp"][-6:], "+05:30")

    def test_health_ok(self):
        """The health endpoint returns 200."""
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assert_meta(payload)


class SystemHealthCheckTests(APITestCase):
    """django-health-check's /health/ (database, cache and the broker's Redis)."""

    # CI has no Redis server, so the broker ping is stubbed.
    @patch.object(Redis, "ping", return_value=True)
    def test_health_ok(self, ping):
        """/health/ returns 200 with every check working."""
        response = self.client.get("/health/?format=json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        self.assertEqual(
            {name.split("(")[0] for name in response.json()},
            {"Database", "Cache", "RedisHealthCheck"},
        )
        ping.assert_called_once()

    @patch.object(Redis, "ping", side_effect=RedisConnectionError)
    def test_redis_down(self, ping):
        """/health/ returns 500 when the broker's Redis is unreachable."""
        response = self.client.get("/health/?format=json")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

    @patch.object(Redis, "ping", return_value=True)
    def test_database_error_stays_in_the_log(self, ping):
        """A database failure returns a generic message; the details are only logged."""
        error = OperationalError('connection to "db.internal" failed for user "dristi"')
        with (
            # Class-wide: the checks run in worker threads with their own connections.
            patch.object(type(connections["default"]), "cursor", side_effect=error),
            self.assertLogs("health-check", "ERROR") as logs,
        ):
            json_response = self.client.get("/health/?format=json")
            html_response = self.client.get("/health/", HTTP_ACCEPT="text/html")
        self.assertEqual(json_response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(
            json_response.json()["Database(alias='default')"],
            "unavailable: Database unavailable.",
        )
        for response in (json_response, html_response):
            self.assertNotIn(b"db.internal", response.content)
        self.assertIn("db.internal", "\n".join(logs.output))

    def test_redis_probe_gets_its_own_bounded_client(self):
        """Each request pings with a new client that has finite timeouts."""
        clients = []
        with patch.object(Redis, "ping", autospec=True, side_effect=clients.append):
            self.client.get("/health/?format=json")
            self.client.get("/health/?format=json")
        self.assertEqual(len(clients), 2)
        self.assertIsNot(clients[0], clients[1])
        options = clients[0].connection_pool.connection_kwargs
        self.assertEqual(options["socket_connect_timeout"], PROBE_TIMEOUT)
        self.assertEqual(options["socket_timeout"], PROBE_TIMEOUT)

    def test_database_probe_gets_its_own_bounded_connection(self):
        """On PostgreSQL the probe connects with a connect and statement timeout."""
        app_settings = connections.settings["default"]
        postgres = {
            "ENGINE": "django.db.backends.postgresql",
            "OPTIONS": {"options": "-c search_path=dristi", "pool": True},
        }
        with patch.dict(app_settings, postgres):
            probe = Database()._probe_connection()
            self.assertIsNot(probe, connections["default"])
            self.assertEqual(probe.settings_dict["OPTIONS"]["connect_timeout"], PROBE_TIMEOUT)
            self.assertEqual(
                probe.settings_dict["OPTIONS"]["options"],
                f"-c search_path=dristi -c statement_timeout={PROBE_TIMEOUT * 1000}",
            )
            self.assertNotIn("pool", probe.settings_dict["OPTIONS"])
            # The app's connections keep their settings.
            self.assertEqual(app_settings["OPTIONS"], postgres["OPTIONS"])

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://localhost:6379/1",
                "OPTIONS": {"db": 1},
            }
        }
    )
    def test_cache_probe_gets_its_own_bounded_client(self):
        """On Redis the cache probe uses a client with finite timeouts."""
        probe = Cache(cache_key=None)._probe_cache()
        self.assertIsNot(probe, caches["default"])
        self.assertEqual(
            probe._options,
            {"db": 1, "socket_connect_timeout": PROBE_TIMEOUT, "socket_timeout": PROBE_TIMEOUT},
        )
        self.assertEqual(caches["default"]._options, {"db": 1})

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://localhost:6379/1",
            }
        }
    )
    @patch.object(Redis, "ping", return_value=True)
    @patch.object(RedisCacheClient, "set", side_effect=RedisTimeoutError)
    def test_cache_timeout(self, cache_set, ping):
        """/health/ returns 500 when the cache's Redis times out."""
        response = self.client.get("/health/?format=json")
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(
            response.json()["Cache(alias='default')"], "unavailable: Cache unavailable."
        )


class APIDocumentationTests(APITestCase):
    """OpenAPI schema and docs endpoint tests."""

    def test_schema_endpoint_is_available(self):
        """The OpenAPI schema endpoint returns 200."""
        response = self.client.get(f"{reverse('api-schema')}?format=json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertIn("openapi", payload)

    def test_schema_generates_without_warnings(self):
        """Schema generation emits no drf-spectacular warnings or errors."""
        call_command("spectacular", "--fail-on-warn", "--validate", stdout=io.StringIO())

    def test_swagger_docs_endpoint_is_available(self):
        """The Swagger docs endpoint returns 200."""
        response = self.client.get(reverse("api-docs"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ApiVersionChangeLogAPITests(APITestCase):
    """API version changelog endpoint tests."""

    def setUp(self):
        self.user = User.objects.create_user(
            mobile_number="+919000000001",
            email="changelog@example.com",
            name="Changelog Reader",
            password="test",
        )

    def test_list_api_version_changelogs(self):
        """The changelog list endpoint returns paginated records for authenticated users."""
        self.client.force_authenticate(user=self.user)
        ApiVersionChangeLog.objects.create(version="v1.0.0", change_log="Initial release")
        response = self.client.get(reverse("api-version-changelog-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)

    def test_retrieve_api_version_changelog(self):
        """The changelog retrieve endpoint returns a single record by UUID for auth users."""
        self.client.force_authenticate(user=self.user)
        changelog = ApiVersionChangeLog.objects.create(
            version="v1.0.1",
            change_log="Added schema and docs endpoints",
        )
        response = self.client.get(
            reverse("api-version-changelog-detail", kwargs={"id": str(changelog.id)})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(changelog.id))
        self.assertEqual(response.json()["version"], "v1.0.1")

    def test_list_requires_authentication(self):
        """The changelog list endpoint rejects anonymous requests."""
        response = self.client.get(reverse("api-version-changelog-list"))
        self.assertIn(
            response.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
        )
