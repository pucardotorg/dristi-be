"""API app tests."""

from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.users.models import User


class HealthCheckTests(APITestCase):
    """Health endpoint tests."""

    def test_health_ok(self):
        """The health endpoint returns 200."""
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "ok")


class UserAPITests(APITestCase):
    """User API tests."""

    def test_list_users(self):
        """The user list endpoint returns users."""
        User.objects.create_user(email="alice@example.com", username="alice", password="test")
        response = self.client.get(reverse("user-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)


class VersionTests(APITestCase):
    """Version endpoint tests."""

    def test_version_returns_git_commit_sha(self):
        """The version endpoint returns the configured Git commit SHA."""
        with override_settings(GIT_COMMIT_SHA="abc123def"):
            response = self.client.get(reverse("version"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["git_version"], "abc123def")

    def test_version_defaults_to_unknown(self):
        """The version endpoint defaults to 'unknown' when not configured."""
        with override_settings(GIT_COMMIT_SHA="unknown"):
            response = self.client.get(reverse("version"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["git_version"], "unknown")


class DemoTaskTests(APITestCase):
    """Demo task endpoint tests."""

    def test_demo_task_requires_email(self):
        """The demo task endpoint requires an email."""
        user = User.objects.create_user(email="test@example.com", username="test", password="test")
        self.client.force_authenticate(user=user)
        response = self.client.post(reverse("demo-task"), {})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
