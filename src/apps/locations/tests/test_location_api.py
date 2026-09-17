"""Tests for the read-only Location API."""

import uuid
from datetime import datetime

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.locations.tests.factories import make_hierarchy, make_state
from apps.users.models import User


class LocationAPITestCase(APITestCase):
    """Shared fixtures for the location endpoints."""

    def setUp(self):
        """Create the IN -> BR -> PATNA chain plus an inactive sibling state."""
        self.india, self.bihar, self.patna = make_hierarchy()
        self.goa = make_state(parent=self.india, code="GA", name="Goa", is_active=False)

    def assert_meta(self, payload):
        """Assert the API response includes the required metadata envelope."""
        self.assertIn("meta", payload)
        self.assertEqual(payload["meta"]["spec_version"], "1.0")
        self.assertIn("app_version", payload["meta"])
        self.assertIn("timestamp", payload["meta"])
        parsed = datetime.fromisoformat(payload["meta"]["timestamp"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(payload["meta"]["timestamp"][-6:], "+05:30")


class LocationListTests(LocationAPITestCase):
    """GET /api/v1/locations/"""

    def test_lists_all_locations(self):
        response = self.client.get(reverse("location-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["count"], 4)
        self.assert_meta(body)

    def test_filters_by_location_type(self):
        response = self.client.get(reverse("location-list"), {"location_type": "state"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = {row["code"] for row in response.json()["results"]}
        self.assertEqual(codes, {"BR", "GA"})

    def test_filters_by_parent_code(self):
        response = self.client.get(reverse("location-list"), {"parent_code": "IN"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = {row["code"] for row in response.json()["results"]}
        self.assertEqual(codes, {"BR", "GA"})

    def test_filters_by_parent_id_and_location_type(self):
        response = self.client.get(
            reverse("location-list"),
            {"parent_id": str(self.bihar.pk), "location_type": "district"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual([row["code"] for row in results], ["PATNA"])

    def test_filters_by_is_active(self):
        response = self.client.get(reverse("location-list"), {"is_active": "false"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.json()["results"]
        self.assertEqual([row["code"] for row in results], ["GA"])

    def test_rejects_both_parent_filters(self):
        response = self.client.get(
            reverse("location-list"),
            {"parent_id": str(self.india.pk), "parent_code": "IN"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_unknown_location_type(self):
        response = self.client.get(reverse("location-list"), {"location_type": "tehsil"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_malformed_parent_id(self):
        response = self.client.get(reverse("location-list"), {"parent_id": "not-a-uuid"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_unknown_parent_code(self):
        response = self.client.get(reverse("location-list"), {"parent_code": "NOPE"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_non_boolean_is_active(self):
        response = self.client.get(reverse("location-list"), {"is_active": "maybe"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LocationRetrieveTests(LocationAPITestCase):
    """GET /api/v1/locations/{id}/ and /locations/code/{code}/"""

    def test_retrieve_by_id(self):
        response = self.client.get(reverse("location-detail", args=[self.patna.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["code"], "PATNA")
        self.assert_meta(body)

    def test_retrieve_by_code(self):
        response = self.client.get(reverse("location-by-code", args=["PATNA"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.patna.pk))

    def test_serialized_payload_includes_parent_code_and_full_name(self):
        response = self.client.get(reverse("location-by-code", args=["PATNA"]))

        body = response.json()
        self.assertEqual(body["parent"], str(self.bihar.pk))
        self.assertEqual(body["parent_code"], "BR")
        self.assertEqual(body["full_name"], "India / Bihar / Patna")
        self.assertTrue(body["is_active"])
        self.assertEqual(body["additional_attributes"], {})

    def test_root_has_null_parent_code(self):
        response = self.client.get(reverse("location-by-code", args=["IN"]))

        body = response.json()
        self.assertIsNone(body["parent"])
        self.assertIsNone(body["parent_code"])
        self.assertEqual(body["full_name"], "India")

    def test_unknown_id_returns_404(self):
        response = self.client.get(reverse("location-detail", args=[uuid.uuid4()]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unknown_code_returns_404(self):
        response = self.client.get(reverse("location-by-code", args=["NOPE"]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LocationChildrenTests(LocationAPITestCase):
    """GET /locations/{id}/children/ and /locations/code/{code}/children/"""

    def test_children_by_id(self):
        response = self.client.get(reverse("location-children", args=[self.india.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        codes = {row["code"] for row in body["results"]}
        self.assertEqual(codes, {"BR", "GA"})
        self.assert_meta(body)

    def test_children_by_code(self):
        response = self.client.get(reverse("location-by-code-children", args=["IN"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = {row["code"] for row in response.json()["results"]}
        self.assertEqual(codes, {"BR", "GA"})

    def test_children_are_direct_only(self):
        response = self.client.get(reverse("location-by-code-children", args=["IN"]))

        codes = {row["code"] for row in response.json()["results"]}
        self.assertNotIn("PATNA", codes)

    def test_leaf_has_no_children(self):
        response = self.client.get(reverse("location-by-code-children", args=["PATNA"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 0)

    def test_children_of_unknown_code_returns_404(self):
        response = self.client.get(reverse("location-by-code-children", args=["NOPE"]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LocationAncestorsTests(LocationAPITestCase):
    """GET /locations/{id}/ancestors/ and /locations/code/{code}/ancestors/"""

    def test_ancestors_by_id_are_root_first(self):
        response = self.client.get(reverse("location-ancestors", args=[self.patna.pk]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual([row["code"] for row in body["data"]], ["IN", "BR"])
        self.assert_meta(body)

    def test_ancestors_by_code_are_root_first(self):
        response = self.client.get(reverse("location-by-code-ancestors", args=["PATNA"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual([row["code"] for row in body["data"]], ["IN", "BR"])
        self.assert_meta(body)

    def test_root_has_no_ancestors(self):
        response = self.client.get(reverse("location-by-code-ancestors", args=["IN"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["data"], [])
        self.assert_meta(body)

    def test_ancestors_of_unknown_code_returns_404(self):
        response = self.client.get(reverse("location-by-code-ancestors", args=["NOPE"]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class LocationWriteMethodTests(LocationAPITestCase):
    """v1 exposes no write endpoints."""

    def test_anonymous_post_is_forbidden(self):
        response = self.client.post(reverse("location-list"), {"code": "MH"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_post_is_not_allowed(self):
        self.client.force_authenticate(user=self._make_user())
        response = self.client.post(reverse("location-list"), {"code": "MH"})

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_session_cookie_post_is_not_allowed(self):
        user = self._make_user()
        self.assertTrue(self.client.login(email=user.email, password="test"))

        response = self.client.post(reverse("location-list"), {"code": "MH"})

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_authenticated_delete_is_not_allowed(self):
        self.client.force_authenticate(user=self._make_user())
        response = self.client.delete(reverse("location-detail", args=[self.patna.pk]))

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def _make_user(self):
        """Create a user for permission-passing write attempts."""
        return User.objects.create_user(
            email="editor@example.com", username="editor", password="test"
        )


class LocationURLPathTests(LocationAPITestCase):
    """The literal paths required by spec 0007 section 6 resolve correctly."""

    def test_spec_paths_resolve(self):
        base = "/api/v1/locations"
        paths = [
            f"{base}/",
            f"{base}/{self.patna.pk}/",
            f"{base}/code/PATNA/",
            f"{base}/{self.india.pk}/children/",
            f"{base}/code/IN/children/",
            f"{base}/{self.patna.pk}/ancestors/",
            f"{base}/code/PATNA/ancestors/",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_code_path_is_not_shadowed_by_detail_lookup(self):
        response = self.client.get("/api/v1/locations/code/BR/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.bihar.pk))
