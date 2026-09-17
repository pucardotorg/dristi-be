"""Tests for the read-only Organization API."""

from datetime import datetime

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.locations.tests.factories import make_hierarchy
from apps.organizations.models import OrganizationType
from apps.organizations.tests.factories import make_organization
from apps.users.models import User


class OrganizationAPITestCase(APITestCase):
    """Base test case that seeds a small organization hierarchy.

    Jurisdictions mirror the IN -> BR -> PATNA example from spec/0008-organization.md
    section 8: the supreme court maps to the country, the high court to the
    state, and the district court to the district.
    """

    def setUp(self):
        self.india, self.bihar, self.patna = make_hierarchy()
        self.root = make_organization(
            code="SUPREME_COURT_INDIA",
            organization_type=OrganizationType.SUPREME_COURT,
            name="Supreme Court of India",
            short_name="SCI",
            jurisdictions=[self.india],
        )
        self.child = make_organization(
            code="PATNA_HIGH_COURT",
            organization_type=OrganizationType.HIGH_COURT,
            name="High Court of Judicature at Patna",
            short_name="Patna HC",
            parent=self.root,
            jurisdictions=[self.bihar],
        )
        self.grandchild = make_organization(
            code="PATNA_DISTRICT_COURT",
            organization_type=OrganizationType.DISTRICT_COURT,
            name="District Court Patna",
            short_name="Patna DC",
            parent=self.child,
            jurisdictions=[self.patna],
        )
        self.inactive = make_organization(
            code="INACTIVE_ORG",
            organization_type=OrganizationType.MAGISTRATE_COURT,
            name="Inactive Org",
            is_active=False,
        )

    def assert_meta(self, payload):
        """Assert the API response includes the required metadata envelope."""
        self.assertIn("meta", payload)
        self.assertEqual(payload["meta"]["spec_version"], "1.0")
        self.assertIn("app_version", payload["meta"])
        self.assertIn("timestamp", payload["meta"])
        parsed = datetime.fromisoformat(payload["meta"]["timestamp"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(payload["meta"]["timestamp"][-6:], "+05:30")


class OrganizationListAPITests(OrganizationAPITestCase):
    """Tests for GET /organizations/."""

    def test_list_returns_all_organizations(self):
        response = self.client.get(reverse("organization-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["count"], 4)
        self.assert_meta(body)

    def test_filter_by_organization_type(self):
        response = self.client.get(
            reverse("organization-list"), {"organization_type": "high_court"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["code"] for item in response.json()["results"]]
        self.assertEqual(codes, ["PATNA_HIGH_COURT"])

    def test_filter_by_parent_id(self):
        response = self.client.get(reverse("organization-list"), {"parent_id": self.root.id})
        codes = [item["code"] for item in response.json()["results"]]
        self.assertEqual(codes, ["PATNA_HIGH_COURT"])

    def test_filter_by_parent_code(self):
        response = self.client.get(
            reverse("organization-list"), {"parent_code": "SUPREME_COURT_INDIA"}
        )
        codes = [item["code"] for item in response.json()["results"]]
        self.assertEqual(codes, ["PATNA_HIGH_COURT"])

    def test_parent_id_and_parent_code_are_mutually_exclusive(self):
        response = self.client.get(
            reverse("organization-list"),
            {"parent_id": self.root.id, "parent_code": "SUPREME_COURT_INDIA"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_malformed_parent_id_returns_400_not_500(self):
        response = self.client.get(reverse("organization-list"), {"parent_id": "not-a-uuid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_organization_type_returns_400(self):
        response = self.client.get(
            reverse("organization-list"), {"organization_type": "not_a_real_type"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_by_is_active_false(self):
        response = self.client.get(reverse("organization-list"), {"is_active": "false"})
        codes = [item["code"] for item in response.json()["results"]]
        self.assertEqual(codes, ["INACTIVE_ORG"])

    def test_filter_by_is_active_true(self):
        response = self.client.get(reverse("organization-list"), {"is_active": "true"})
        codes = [item["code"] for item in response.json()["results"]]
        self.assertNotIn("INACTIVE_ORG", codes)

    def test_invalid_is_active_value_returns_400(self):
        response = self.client.get(reverse("organization-list"), {"is_active": "maybe"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_by_jurisdiction_id(self):
        response = self.client.get(reverse("organization-list"), {"jurisdiction_id": self.bihar.id})
        codes = [item["code"] for item in response.json()["results"]]
        self.assertEqual(codes, ["PATNA_HIGH_COURT"])

    def test_filter_by_jurisdiction_code(self):
        response = self.client.get(reverse("organization-list"), {"jurisdiction_code": "BR"})
        codes = [item["code"] for item in response.json()["results"]]
        self.assertEqual(codes, ["PATNA_HIGH_COURT"])

    def test_jurisdiction_id_and_jurisdiction_code_are_mutually_exclusive(self):
        response = self.client.get(
            reverse("organization-list"),
            {"jurisdiction_id": self.bihar.id, "jurisdiction_code": "BR"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_malformed_jurisdiction_id_returns_400_not_500(self):
        response = self.client.get(reverse("organization-list"), {"jurisdiction_id": "not-a-uuid"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class OrganizationDetailAPITests(OrganizationAPITestCase):
    """Tests for GET /organizations/{id}/ and /organizations/code/{code}/."""

    def test_retrieve_by_id(self):
        response = self.client.get(reverse("organization-detail", args=[self.root.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["code"], "SUPREME_COURT_INDIA")
        self.assert_meta(body)

    def test_retrieve_by_id_not_found(self):
        response = self.client.get(
            reverse("organization-detail", args=["00000000-0000-0000-0000-000000000000"])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_by_code(self):
        response = self.client.get(
            reverse("organization-by-code", kwargs={"code": "PATNA_HIGH_COURT"})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "High Court of Judicature at Patna")

    def test_retrieve_by_code_not_found(self):
        response = self.client.get(reverse("organization-by-code", kwargs={"code": "NO_SUCH_CODE"}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_response_includes_parent_code(self):
        response = self.client.get(
            reverse("organization-by-code", kwargs={"code": "PATNA_HIGH_COURT"})
        )
        self.assertEqual(response.json()["parent_code"], "SUPREME_COURT_INDIA")

    def test_root_organization_has_null_parent_code(self):
        response = self.client.get(
            reverse("organization-by-code", kwargs={"code": "SUPREME_COURT_INDIA"})
        )
        self.assertIsNone(response.json()["parent_code"])

    def test_response_includes_jurisdiction_codes(self):
        response = self.client.get(
            reverse("organization-by-code", kwargs={"code": "PATNA_HIGH_COURT"})
        )
        self.assertEqual(response.json()["jurisdiction_codes"], ["BR"])

    def test_jurisdiction_codes_empty_when_none_assigned(self):
        response = self.client.get(reverse("organization-by-code", kwargs={"code": "INACTIVE_ORG"}))
        self.assertEqual(response.json()["jurisdiction_codes"], [])


class OrganizationChildrenAPITests(OrganizationAPITestCase):
    """Tests for the children sub-resource, by id and by code."""

    def test_children_by_id(self):
        response = self.client.get(reverse("organization-children", args=[self.root.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        codes = [item["code"] for item in body["data"]]
        self.assertEqual(codes, ["PATNA_HIGH_COURT"])
        self.assert_meta(body)

    def test_children_by_code(self):
        response = self.client.get(
            reverse("organization-by-code-children", kwargs={"code": "SUPREME_COURT_INDIA"})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["code"] for item in response.json()["data"]]
        self.assertEqual(codes, ["PATNA_HIGH_COURT"])

    def test_children_empty_for_leaf_organization(self):
        response = self.client.get(reverse("organization-children", args=[self.grandchild.id]))
        self.assertEqual(response.json()["data"], [])

    def test_children_by_code_not_found(self):
        response = self.client.get(
            reverse("organization-by-code-children", kwargs={"code": "NO_SUCH_CODE"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class OrganizationAncestorsAPITests(OrganizationAPITestCase):
    """Tests for the ancestors sub-resource, by id and by code."""

    def test_ancestors_by_id(self):
        response = self.client.get(reverse("organization-ancestors", args=[self.grandchild.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        codes = [item["code"] for item in body["data"]]
        self.assertEqual(codes, ["SUPREME_COURT_INDIA", "PATNA_HIGH_COURT"])
        self.assert_meta(body)

    def test_ancestors_by_code(self):
        response = self.client.get(
            reverse("organization-by-code-ancestors", kwargs={"code": "PATNA_DISTRICT_COURT"})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["code"] for item in response.json()["data"]]
        self.assertEqual(codes, ["SUPREME_COURT_INDIA", "PATNA_HIGH_COURT"])

    def test_ancestors_empty_for_root(self):
        response = self.client.get(reverse("organization-ancestors", args=[self.root.id]))
        self.assertEqual(response.json()["data"], [])

    def test_ancestors_by_code_not_found(self):
        response = self.client.get(
            reverse("organization-by-code-ancestors", kwargs={"code": "NO_SUCH_CODE"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class OrganizationJurisdictionsAPITests(OrganizationAPITestCase):
    """Tests for the jurisdictions sub-resource, by id and by code."""

    def test_jurisdictions_by_id(self):
        response = self.client.get(reverse("organization-jurisdictions", args=[self.child.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        codes = [item["code"] for item in body["data"]]
        self.assertEqual(codes, ["BR"])
        self.assert_meta(body)

    def test_jurisdictions_by_code(self):
        response = self.client.get(
            reverse("organization-by-code-jurisdictions", kwargs={"code": "PATNA_DISTRICT_COURT"})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["code"] for item in response.json()["data"]]
        self.assertEqual(codes, ["PATNA"])

    def test_jurisdictions_empty_when_none_assigned(self):
        response = self.client.get(reverse("organization-jurisdictions", args=[self.inactive.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["data"], [])

    def test_jurisdictions_by_id_not_found(self):
        response = self.client.get(
            reverse(
                "organization-jurisdictions",
                args=["00000000-0000-0000-0000-000000000000"],
            )
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_jurisdictions_by_code_not_found(self):
        response = self.client.get(
            reverse("organization-by-code-jurisdictions", kwargs={"code": "NO_SUCH_CODE"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class OrganizationWriteMethodTests(OrganizationAPITestCase):
    """v1 exposes no write endpoints."""

    def test_anonymous_post_is_forbidden(self):
        response = self.client.post(reverse("organization-list"), {"code": "NEW_ORG"})

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_authenticated_post_is_not_allowed(self):
        self.client.force_authenticate(user=self._make_user())
        response = self.client.post(reverse("organization-list"), {"code": "NEW_ORG"})

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_session_cookie_post_is_not_allowed(self):
        user = self._make_user()
        self.assertTrue(self.client.login(email=user.email, password="test"))

        response = self.client.post(reverse("organization-list"), {"code": "NEW_ORG"})

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_authenticated_delete_is_not_allowed(self):
        self.client.force_authenticate(user=self._make_user())
        response = self.client.delete(reverse("organization-detail", args=[self.root.id]))

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def _make_user(self):
        """Create a user for permission-passing write attempts."""
        return User.objects.create_user(
            email="editor@example.com", username="editor", password="test"
        )


class OrganizationURLPathTests(OrganizationAPITestCase):
    """The literal paths required by spec 0008 section 7 resolve correctly."""

    def test_spec_paths_resolve(self):
        base = "/api/v1/organizations"
        paths = [
            f"{base}/",
            f"{base}/{self.root.id}/",
            f"{base}/code/SUPREME_COURT_INDIA/",
            f"{base}/{self.root.id}/children/",
            f"{base}/code/SUPREME_COURT_INDIA/children/",
            f"{base}/{self.grandchild.id}/ancestors/",
            f"{base}/code/PATNA_DISTRICT_COURT/ancestors/",
            f"{base}/{self.child.id}/jurisdictions/",
            f"{base}/code/PATNA_HIGH_COURT/jurisdictions/",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_code_path_is_not_shadowed_by_detail_lookup(self):
        response = self.client.get("/api/v1/organizations/code/PATNA_HIGH_COURT/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(self.child.id))
