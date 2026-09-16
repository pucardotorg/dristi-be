"""Tests for the Location model."""

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from apps.locations.models import Location


def make_location(**overrides):
    """Create a location with sensible defaults for tests."""
    data = {
        "code": "IN",
        "name": "India",
        "short_name": "IN",
        "location_type": Location.LocationType.COUNTRY,
        "parent": None,
        "additional_attributes": {},
    }
    data.update(overrides)
    return Location.objects.create(**data)


def make_hierarchy():
    """Create the IN -> BR -> PATNA chain from the spec example."""
    india = make_location()
    bihar = make_location(
        code="BR",
        name="Bihar",
        short_name="BR",
        location_type=Location.LocationType.STATE,
        parent=india,
    )
    patna = make_location(
        code="PATNA",
        name="Patna",
        short_name="Patna",
        location_type=Location.LocationType.DISTRICT,
        parent=bihar,
    )
    return india, bihar, patna


@pytest.mark.django_db
class TestLocationCreation:
    """Creation and default behaviour."""

    def test_creates_country_state_district_chain(self):
        india, bihar, patna = make_hierarchy()

        assert india.parent is None
        assert bihar.parent == india
        assert patna.parent == bihar

    def test_defaults_to_active(self):
        assert make_location().is_active is True

    def test_short_name_is_optional(self):
        location = make_location(short_name="")

        assert location.short_name == ""

    def test_str_includes_name_and_code(self):
        assert str(make_location()) == "India (IN)"


@pytest.mark.django_db
class TestCodeValidation:
    """Code format and uniqueness rules."""

    @pytest.mark.parametrize("code", ["in", "In", "IN-BR", "IN BR", "IN.BR", ""])
    def test_rejects_invalid_codes(self, code):
        with pytest.raises(ValidationError) as exc_info:
            make_location(code=code)

        assert "code" in exc_info.value.message_dict

    @pytest.mark.parametrize("code", ["IN", "IN_BR_PATNA", "PATNA", "D1", "IN_2"])
    def test_accepts_valid_codes(self, code):
        assert make_location(code=code).code == code

    def test_does_not_silently_normalise_code(self):
        with pytest.raises(ValidationError):
            make_location(code="in")

        assert not Location.objects.filter(code="IN").exists()

    def test_rejects_duplicate_code(self):
        make_location()

        with pytest.raises(ValidationError) as exc_info:
            make_location(name="India again")

        assert "code" in exc_info.value.message_dict


@pytest.mark.django_db
class TestLocationTypeValidation:
    """Location type rules."""

    def test_rejects_unknown_location_type(self):
        with pytest.raises(ValidationError) as exc_info:
            make_location(location_type="tehsil")

        assert "location_type" in exc_info.value.message_dict

    def test_accepts_every_supported_type(self):
        for index, value in enumerate(Location.LocationType.values):
            location = make_location(code=f"C{index}", location_type=value)
            assert location.location_type == value


@pytest.mark.django_db
class TestParentValidation:
    """Self-parenting and cycle rules."""

    def test_rejects_self_as_parent(self):
        india = make_location()
        india.parent = india

        with pytest.raises(ValidationError) as exc_info:
            india.save()

        assert "parent" in exc_info.value.message_dict

    def test_rejects_two_node_cycle(self):
        india = make_location()
        bihar = make_location(
            code="BR",
            name="Bihar",
            location_type=Location.LocationType.STATE,
            parent=india,
        )
        india.parent = bihar

        with pytest.raises(ValidationError) as exc_info:
            india.save()

        assert "parent" in exc_info.value.message_dict

    def test_rejects_three_node_cycle(self):
        india, bihar, patna = make_hierarchy()
        india.parent = patna

        with pytest.raises(ValidationError) as exc_info:
            india.save()

        assert "parent" in exc_info.value.message_dict

    def test_allows_many_children_under_one_parent(self):
        india = make_location()
        make_location(
            code="BR", name="Bihar", location_type=Location.LocationType.STATE, parent=india
        )
        make_location(
            code="MH", name="Maharashtra", location_type=Location.LocationType.STATE, parent=india
        )

        assert india.children.count() == 2


@pytest.mark.django_db
class TestHierarchyMethods:
    """Hierarchy helper methods."""

    def test_is_root(self):
        india, bihar, _ = make_hierarchy()

        assert india.is_root() is True
        assert bihar.is_root() is False

    def test_get_ancestors_is_ordered_root_first(self):
        india, bihar, patna = make_hierarchy()

        assert patna.get_ancestors() == [india, bihar]

    def test_get_ancestors_is_empty_for_root(self):
        india, _, _ = make_hierarchy()

        assert india.get_ancestors() == []

    def test_get_descendants_returns_all_nested_children(self):
        india, bihar, patna = make_hierarchy()

        descendants = india.get_descendants()

        assert set(descendants) == {bihar, patna}

    def test_get_descendants_is_empty_for_leaf(self):
        _, _, patna = make_hierarchy()

        assert patna.get_descendants() == []

    def test_get_full_name(self):
        india, bihar, patna = make_hierarchy()

        assert india.get_full_name() == "India"
        assert bihar.get_full_name() == "India / Bihar"
        assert patna.get_full_name() == "India / Bihar / Patna"


@pytest.mark.django_db
class TestDeletionProtection:
    """PROTECT behaviour on the parent foreign key."""

    def test_cannot_delete_parent_with_children(self):
        india, _, _ = make_hierarchy()

        with pytest.raises(ProtectedError):
            india.delete()

        assert Location.objects.filter(code="IN").exists()

    def test_can_delete_leaf(self):
        _, _, patna = make_hierarchy()

        patna.delete()

        assert not Location.objects.filter(code="PATNA").exists()


@pytest.mark.django_db
class TestActivatableManager:
    """The inherited ActivatableQuerySet helpers."""

    def test_active_and_inactive(self):
        active = make_location()
        inactive = make_location(
            code="BR",
            name="Bihar",
            location_type=Location.LocationType.STATE,
            is_active=False,
        )

        assert active in Location.objects.active()
        assert inactive not in Location.objects.active()
        assert inactive in Location.objects.inactive()
        assert Location.objects.count() == 2
