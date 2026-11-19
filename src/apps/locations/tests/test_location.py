"""Tests for the Location model."""

import pytest
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError

from apps.locations.models import Location
from apps.locations.tests.factories import (
    define_address_attribute,
    make_bank,
    make_hierarchy,
    make_location,
    make_state,
)


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
        district = make_location(code="D", location_type=Location.LocationType.DISTRICT)
        # Leaf types need a parent; a bank's code is its IFSC.
        leaf_overrides = {
            Location.LocationType.PINCODE: {"parent": district},
            Location.LocationType.BANK: {"parent": district, "code": "SBIN0001234"},
        }
        for index, value in enumerate(Location.LocationType.values):
            fields = {"code": f"C{index}", **leaf_overrides.get(value, {})}
            location = make_location(location_type=value, **fields)
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
        bihar = make_state(parent=india)
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

    @pytest.mark.parametrize("parent_level", ["none", "state"])
    def test_pincode_must_be_under_a_district(self, parent_level):
        india, bihar, _patna = make_hierarchy()
        parent = {"none": None, "state": bihar}[parent_level]

        with pytest.raises(ValidationError) as exc_info:
            make_location(
                code="PIN_800001",
                name="800001",
                location_type=Location.LocationType.PINCODE,
                parent=parent,
            )

        assert "parent" in exc_info.value.message_dict

    def make_pincode(self, district):
        """Create pincode 800001 under ``district``."""
        return make_location(
            code="PIN_800001",
            name="800001",
            location_type=Location.LocationType.PINCODE,
            parent=district,
        )

    def test_nothing_can_be_put_under_a_pincode(self):
        _india, _bihar, patna = make_hierarchy()
        pincode = self.make_pincode(patna)

        with pytest.raises(ValidationError) as exc_info:
            make_location(
                code="NALANDA",
                name="Nalanda",
                location_type=Location.LocationType.DISTRICT,
                parent=pincode,
            )

        assert "A pincode cannot have locations under it." in exc_info.value.message_dict["parent"]

    def test_district_holding_pincodes_cannot_change_type(self):
        _india, _bihar, patna = make_hierarchy()
        self.make_pincode(patna)
        patna.location_type = Location.LocationType.STATE

        with pytest.raises(ValidationError) as exc_info:
            patna.save()

        assert "location_type" in exc_info.value.message_dict

    def test_location_with_children_cannot_become_a_pincode(self):
        # A location under a district, so only the "has children" rule applies.
        _india, _bihar, patna = make_hierarchy()
        area = make_location(
            code="AREA", name="Area", location_type=Location.LocationType.DISTRICT, parent=patna
        )
        make_location(
            code="SUB_AREA",
            name="Sub area",
            location_type=Location.LocationType.DISTRICT,
            parent=area,
        )
        area.location_type = Location.LocationType.PINCODE

        with pytest.raises(ValidationError) as exc_info:
            area.full_clean()

        assert exc_info.value.message_dict["location_type"] == [
            "A location with locations under it cannot be a pincode."
        ]

    def test_district_without_pincodes_can_still_change_type(self):
        _india, bihar, patna = make_hierarchy()
        patna.location_type = Location.LocationType.STATE
        patna.parent = None

        patna.save()

        assert Location.objects.get(pk=patna.pk).location_type == Location.LocationType.STATE

    def test_pincode_under_a_district_is_valid(self):
        _india, _bihar, patna = make_hierarchy()

        pincode = make_location(
            code="PIN_800001",
            name="800001",
            location_type=Location.LocationType.PINCODE,
            parent=patna,
        )

        assert pincode.get_full_name() == "India / Bihar / Patna / 800001"

    def test_allows_many_children_under_one_parent(self):
        india = make_location()
        make_state(parent=india)
        make_state(parent=india, code="MH", name="Maharashtra")

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
        inactive = make_state(is_active=False)

        assert active in Location.objects.active()
        assert inactive not in Location.objects.active()
        assert inactive in Location.objects.inactive()
        assert Location.objects.count() == 2


@pytest.mark.django_db
class TestBankValidation:
    """A bank is an IFSC-keyed leaf under a district (issue #249)."""

    def test_bank_under_a_district_is_valid(self):
        _india, _bihar, patna = make_hierarchy()

        bank = make_bank(patna)

        assert bank.parent == patna

    def test_full_name_runs_through_the_district(self):
        _india, _bihar, patna = make_hierarchy()

        bank = make_bank(patna)

        assert bank.get_full_name() == "India / Bihar / Patna / State Bank of India - Patna Main"

    @pytest.mark.parametrize("parent_level", ["none", "country", "state", "pincode"])
    def test_bank_must_be_under_a_district(self, parent_level):
        india, bihar, patna = make_hierarchy()
        pincode = make_location(
            code="PIN_800001",
            name="800001",
            location_type=Location.LocationType.PINCODE,
            parent=patna,
        )
        parent = {"none": None, "country": india, "state": bihar, "pincode": pincode}[parent_level]

        with pytest.raises(ValidationError) as exc_info:
            make_bank(parent)

        assert exc_info.value.message_dict["parent"] == ["A bank must be under a district."]

    def test_nothing_can_be_put_under_a_bank(self):
        _india, _bihar, patna = make_hierarchy()
        bank = make_bank(patna)

        with pytest.raises(ValidationError) as exc_info:
            make_location(
                code="NALANDA",
                name="Nalanda",
                location_type=Location.LocationType.DISTRICT,
                parent=bank,
            )

        assert exc_info.value.message_dict["parent"] == ["A bank cannot have locations under it."]

    @pytest.mark.parametrize("code", ["SBIN1001234", "SBI0001234", "SBIN00012345", "PIN_800001"])
    def test_code_must_be_an_ifsc(self, code):
        _india, _bihar, patna = make_hierarchy()

        with pytest.raises(ValidationError) as exc_info:
            make_bank(patna, code=code)

        assert "code" in exc_info.value.message_dict

    def test_bank_follows_the_issue_shape(self):
        _india, _bihar, patna = make_hierarchy()

        bank = make_bank(patna)

        assert (bank.code, bank.short_name) == ("SBIN0001234", "SBIN0001234")
        assert bank.name == "State Bank of India - Patna Main"
        # Nothing about the bank's details is required.
        assert bank.additional_attributes == {}

    def test_bank_stores_its_address_once_the_attribute_is_defined(self):
        define_address_attribute()
        _india, _bihar, patna = make_hierarchy()

        bank = make_bank(patna, address="Fraser Road, Patna 800001")

        bank.refresh_from_db()
        assert bank.additional_attributes == {"address": "Fraser Road, Patna 800001"}

    def test_address_is_rejected_until_the_attribute_is_defined(self):
        _india, _bihar, patna = make_hierarchy()

        with pytest.raises(ValidationError) as exc_info:
            make_bank(patna, address="Fraser Road, Patna 800001")

        assert "additional_attributes" in exc_info.value.message_dict

    @pytest.mark.parametrize(
        "new_type", [Location.LocationType.STATE, Location.LocationType.COUNTRY]
    )
    def test_district_holding_banks_must_stay_a_district(self, new_type):
        _india, _bihar, patna = make_hierarchy()
        make_bank(patna)
        patna.location_type = new_type
        patna.parent = None

        with pytest.raises(ValidationError) as exc_info:
            patna.full_clean()

        assert exc_info.value.message_dict["location_type"] == [
            "A location with banks under it must stay a district."
        ]

    def test_location_with_children_cannot_become_a_bank(self):
        # Area sits under a district, so only the "has children" rule applies.
        _india, _bihar, patna = make_hierarchy()
        area = make_location(
            code="AREA", name="Area", location_type=Location.LocationType.DISTRICT, parent=patna
        )
        make_location(
            code="SUB_AREA",
            name="Sub area",
            location_type=Location.LocationType.DISTRICT,
            parent=area,
        )
        area.code = "SBIN0001234"
        area.location_type = Location.LocationType.BANK

        with pytest.raises(ValidationError) as exc_info:
            area.full_clean()

        assert exc_info.value.message_dict["location_type"] == [
            "A location with locations under it cannot be a bank."
        ]
