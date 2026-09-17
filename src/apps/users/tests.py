"""Users app API tests."""

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from .models import User


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
