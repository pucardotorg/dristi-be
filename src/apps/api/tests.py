"""API app tests."""

import json
from datetime import datetime

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

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


class UserAPITests(APITestCase):
    """User API tests."""

    def test_list_users(self):
        """The user list endpoint returns users."""
        User.objects.create_user(email="alice@example.com", username="alice", password="test")
        response = self.client.get(reverse("user-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["count"], 1)
        self.assertIn("meta", payload)


class APIDocumentationTests(APITestCase):
    """OpenAPI schema and docs endpoint tests."""

    def test_schema_endpoint_is_available(self):
        """The OpenAPI schema endpoint returns 200."""
        response = self.client.get(f"{reverse('api-schema')}?format=json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = json.loads(response.content.decode("utf-8"))
        self.assertIn("openapi", payload)

    def test_swagger_docs_endpoint_is_available(self):
        """The Swagger docs endpoint returns 200."""
        response = self.client.get(reverse("api-docs"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ApiVersionChangeLogAPITests(APITestCase):
    """API version changelog endpoint tests."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="changelog@example.com",
            username="changelog",
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
