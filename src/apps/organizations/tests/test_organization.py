"""Tests for the Organization model."""

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from apps.locations.tests.factories import make_hierarchy
from apps.organizations.tests.factories import make_organization


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
