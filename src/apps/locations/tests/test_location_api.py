"""Tests for the read-only Location API."""

import uuid

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.locations.models import Location
from apps.users.models import User


class LocationAPITestCase(APITestCase):
    """Shared fixtures for the location endpoints."""

    def setUp(self):
        """Create the IN -> BR -> PATNA chain plus an inactive sibling state."""
        self.india = Location.objects.create(
            code="IN",
            name="India",
            short_name="IN",
            location_type=Location.LocationType.COUNTRY,
            additional_attributes={},
        )
        self.bihar = Location.objects.create(
            code="BR",
            name="Bihar",
            short_name="BR",
            location_type=Location.LocationType.STATE,
            parent=self.india,
            additional_attributes={},
        )
        self.patna = Location.objects.create(
            code="PATNA",
            name="Patna",
            short_name="Patna",
            location_type=Location.LocationType.DISTRICT,
            parent=self.bihar,
            additional_attributes={},
        )
        self.goa = Location.objects.create(
            code="GA",
            name="Goa",
            short_name="GA",
            location_type=Location.LocationType.STATE,
            parent=self.india,
            is_active=False,
            additional_attributes={},
        )


class LocationListTests(LocationAPITestCase):
    """GET /api/v1/locations/"""

    def test_lists_all_locations(self):
        response = self.client.get(reverse("location-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 4)

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
        self.assertEqual(response.json()["code"], "PATNA")

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
        codes = {row["code"] for row in response.json()["results"]}
        self.assertEqual(codes, {"BR", "GA"})

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
        self.assertEqual([row["code"] for row in response.json()], ["IN", "BR"])

    def test_ancestors_by_code_are_root_first(self):
        response = self.client.get(reverse("location-by-code-ancestors", args=["PATNA"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([row["code"] for row in response.json()], ["IN", "BR"])

    def test_root_has_no_ancestors(self):
        response = self.client.get(reverse("location-by-code-ancestors", args=["IN"]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), [])

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
