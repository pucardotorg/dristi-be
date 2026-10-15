"""Tests for the read-only Person and Institution serializers."""

import pytest

from apps.parties.serializers import InstitutionSerializer, PersonSerializer
from apps.parties.tests.factories import make_address, make_institution, make_person
from apps.users.models import User

pytestmark = pytest.mark.django_db


def test_person_output_nests_institution_and_addresses():
    address = make_address()
    institution = make_institution(address=address)
    person = make_person(
        institution=institution,
        designation="Director",
        permanent_address=address,
        correspondence_address=address,
    )

    data = PersonSerializer(person).data

    assert data["institution"]["entity_name"] == institution.entity_name
    assert data["institution"]["address"]["line1"] == address.line1
    assert data["permanent_address"]["id"] == str(address.id)


def test_person_without_institution_or_addresses_has_nulls():
    data = PersonSerializer(make_person()).data

    assert data["institution"] is None
    assert data["permanent_address"] is None
    assert data["correspondence_address"] is None


@pytest.mark.parametrize("serializer_class", [PersonSerializer, InstitutionSerializer])
def test_who_entered_the_record_is_not_exposed(serializer_class):
    # Often entered by the other side; revealing who would leak it.
    clerk = User.objects.create_user(mobile_number="+919876543210", name="Opposing Clerk")
    record = (
        make_person(created_by=clerk, updated_by=clerk)
        if serializer_class is PersonSerializer
        else make_institution(created_by=clerk, updated_by=clerk)
    )

    data = serializer_class(record).data

    assert not {"created_by", "updated_by"} & set(data)
    assert "Opposing Clerk" not in str(data)


def test_input_is_ignored():
    serializer = PersonSerializer(data={"name": "Ravi"})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {}
