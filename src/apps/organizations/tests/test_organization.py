"""Tests for the Organization model and read-only API."""

from datetime import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.locations.tests.factories import make_hierarchy
from apps.organizations.models import Organization, OrganizationType


def make_organization(**kwargs):
    """Create an Organization with sensible defaults for tests."""
    jurisdictions = kwargs.pop("jurisdictions", None)
    defaults = {
        "code": "TEST_ORG",
        "organization_type": OrganizationType.HIGH_COURT,
        "name": "Test Organization",
    }
    defaults.update(kwargs)
    org = Organization.objects.create(**defaults)
    if jurisdictions is not None:
        org.jurisdictions.set(jurisdictions)
    return org


@pytest.mark.django_db
class TestOrganizationModel:
    """Tests for Organization validation and hierarchy helpers."""

    def test_code_must_be_uppercase_snake_case(self):
        with pytest.raises(ValidationError):
            make_organization(code="not-valid")

    def test_valid_code_is_accepted(self):
        org = make_organization(code="VALID_CODE_1")
        assert org.code == "VALID_CODE_1"

    def test_organization_type_must_be_a_supported_choice(self):
        with pytest.raises(ValidationError):
            make_organization(code="BAD_TYPE_ORG", organization_type="not_a_real_type")

    def test_organization_cannot_be_its_own_parent(self):
        org = make_organization(code="SELF_PARENT")
        org.parent_id = org.id
        with pytest.raises(ValidationError):
            org.full_clean()

    def test_circular_parent_chain_is_rejected(self):
        root = make_organization(code="ROOT_ORG")
        child = make_organization(code="CHILD_ORG", parent=root)

        root.parent = child
        with pytest.raises(ValidationError):
            root.save()

    def test_is_root_true_when_no_parent(self):
        org = make_organization(code="ROOT_ONLY")
        assert org.is_root() is True

    def test_is_root_false_when_parent_set(self):
        root = make_organization(code="ROOT_2")
        child = make_organization(code="CHILD_2", parent=root)
        assert child.is_root() is False

    def test_get_ancestors_returns_root_to_immediate_parent(self):
        root = make_organization(code="ANC_ROOT")
        mid = make_organization(code="ANC_MID", parent=root)
        leaf = make_organization(code="ANC_LEAF", parent=mid)

        assert leaf.get_ancestors() == [root, mid]

    def test_get_ancestors_empty_for_root(self):
        root = make_organization(code="ANC_ROOT_2")
        assert root.get_ancestors() == []

    def test_get_descendants_returns_nested_children(self):
        root = make_organization(code="DESC_ROOT")
        child = make_organization(code="DESC_CHILD", parent=root)
        grandchild = make_organization(code="DESC_GRANDCHILD", parent=child)

        descendants = root.get_descendants()

        assert child in descendants
        assert grandchild in descendants
        assert len(descendants) == 2

    def test_get_full_name_concatenates_ancestor_names(self):
        root = make_organization(code="NAME_ROOT", name="India Supreme Court")
        child = make_organization(code="NAME_CHILD", name="Patna Bench", parent=root)

        assert child.get_full_name() == "India Supreme Court / Patna Bench"

    def test_str_returns_code(self):
        org = make_organization(code="STR_CODE")
        assert str(org) == "STR_CODE"

    def test_parent_protected_from_deletion_while_children_exist(self):
        root = make_organization(code="PROTECT_ROOT")
        make_organization(code="PROTECT_CHILD", parent=root)

        with pytest.raises(ProtectedError):
            root.delete()

    def test_jurisdictions_can_be_assigned(self):
        india, bihar, patna = make_hierarchy()
        org = make_organization(code="JURIS_ORG", jurisdictions=[bihar, patna])

        assert set(org.jurisdictions.values_list("code", flat=True)) == {"BR", "PATNA"}

    def test_jurisdictions_default_to_empty(self):
        org = make_organization(code="NO_JURIS_ORG")
        assert org.jurisdictions.count() == 0


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
        self.assertEqual(response.json()["count"], 4)

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
        self.assertEqual(response.json()["code"], "SUPREME_COURT_INDIA")

    def test_retrieve_by_id_not_found(self):
        response = self.client.get(
            reverse("organization-detail", args=["00000000-0000-0000-0000-000000000000"])
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_by_code(self):
        response = self.client.get(
            reverse("organization-code-detail", kwargs={"code": "PATNA_HIGH_COURT"})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "High Court of Judicature at Patna")

    def test_retrieve_by_code_not_found(self):
        response = self.client.get(
            reverse("organization-code-detail", kwargs={"code": "NO_SUCH_CODE"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_response_includes_parent_code(self):
        response = self.client.get(
            reverse("organization-code-detail", kwargs={"code": "PATNA_HIGH_COURT"})
        )
        self.assertEqual(response.json()["parent_code"], "SUPREME_COURT_INDIA")

    def test_root_organization_has_null_parent_code(self):
        response = self.client.get(
            reverse("organization-code-detail", kwargs={"code": "SUPREME_COURT_INDIA"})
        )
        self.assertIsNone(response.json()["parent_code"])

    def test_response_includes_jurisdiction_codes(self):
        response = self.client.get(
            reverse("organization-code-detail", kwargs={"code": "PATNA_HIGH_COURT"})
        )
        self.assertEqual(response.json()["jurisdiction_codes"], ["BR"])

    def test_jurisdiction_codes_empty_when_none_assigned(self):
        response = self.client.get(
            reverse("organization-code-detail", kwargs={"code": "INACTIVE_ORG"})
        )
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
            reverse("organization-code-children", kwargs={"code": "SUPREME_COURT_INDIA"})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["code"] for item in response.json()["data"]]
        self.assertEqual(codes, ["PATNA_HIGH_COURT"])

    def test_children_empty_for_leaf_organization(self):
        response = self.client.get(reverse("organization-children", args=[self.grandchild.id]))
        self.assertEqual(response.json()["data"], [])

    def test_children_by_code_not_found(self):
        response = self.client.get(
            reverse("organization-code-children", kwargs={"code": "NO_SUCH_CODE"})
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
            reverse("organization-code-ancestors", kwargs={"code": "PATNA_DISTRICT_COURT"})
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        codes = [item["code"] for item in response.json()["data"]]
        self.assertEqual(codes, ["SUPREME_COURT_INDIA", "PATNA_HIGH_COURT"])

    def test_ancestors_empty_for_root(self):
        response = self.client.get(reverse("organization-ancestors", args=[self.root.id]))
        self.assertEqual(response.json()["data"], [])

    def test_ancestors_by_code_not_found(self):
        response = self.client.get(
            reverse("organization-code-ancestors", kwargs={"code": "NO_SUCH_CODE"})
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
            reverse("organization-code-jurisdictions", kwargs={"code": "PATNA_DISTRICT_COURT"})
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
            reverse("organization-code-jurisdictions", kwargs={"code": "NO_SUCH_CODE"})
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
