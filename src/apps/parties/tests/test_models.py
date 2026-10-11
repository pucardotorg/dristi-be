"""Tests for the Person and Institution models (spec 0020 §2-3)."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.parties.models import Institution, Person, VerificationLevel
from apps.parties.tests.factories import make_address, make_institution, make_person
from apps.users.models import User


@pytest.mark.django_db
class TestPerson:
    """Person validation and database constraints."""

    def test_defaults_to_asserted_with_no_user(self):
        person = make_person()

        assert person.verification_level == VerificationLevel.ASSERTED
        assert person.user is None

    def test_phone_number_may_be_null(self):
        person = Person(name="No Phone")

        person.full_clean()

    def test_valid_indian_mobile_is_accepted(self):
        person = Person(name="Has Phone", phone_number="+919876543210")

        person.full_clean()

    @pytest.mark.parametrize("number", ["9876543210", "+915876543210", "+91987654321"])
    def test_invalid_phone_number_fails_validation(self, number):
        person = Person(name="Bad Phone", phone_number=number)

        with pytest.raises(ValidationError) as exc:
            person.full_clean()

        assert "phone_number" in exc.value.message_dict

    def test_database_rejects_invalid_phone_number(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            Person.objects.create(name="Bad Phone", phone_number="12345")

    def test_designation_without_institution_is_invalid(self):
        person = Person(name="Director", designation="Director")

        with pytest.raises(ValidationError) as exc:
            person.full_clean()

        assert "designation" in exc.value.message_dict

    def test_designation_with_institution_is_valid(self):
        person = Person(name="Director", designation="Director", institution=make_institution())

        person.full_clean()

    def test_user_can_be_claimed_by_only_one_person(self):
        user = User.objects.create_user(mobile_number="+919876543210")
        make_person(user=user)

        with pytest.raises(IntegrityError), transaction.atomic():
            make_person(name="Duplicate", user=user)

    def test_database_rejects_unknown_verification_level(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            Person.objects.create(name="Bad Level", verification_level="GUESSED")

    def test_both_addresses_can_point_at_the_same_row(self):
        address = make_address()
        person = make_person(permanent_address=address, correspondence_address=address)

        assert person.permanent_address_id == person.correspondence_address_id == address.id

    def test_institution_with_people_cannot_be_deleted(self):
        institution = make_institution()
        make_person(institution=institution, designation="Director")

        with pytest.raises(ProtectedError):
            institution.delete()


@pytest.mark.django_db
class TestInstitution:
    """Institution validation and database constraints."""

    def test_contact_number_accepts_a_landline(self):
        institution = make_institution(contact_number="08022334455")

        institution.full_clean()

    def test_unknown_entity_type_fails_validation(self):
        institution = make_institution()
        institution.entity_type = "NOT_A_TYPE"

        with pytest.raises(ValidationError) as exc:
            institution.full_clean()

        assert "entity_type" in exc.value.message_dict

    def test_database_rejects_unknown_entity_type(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            Institution.objects.create(entity_type="NOT_A_TYPE", entity_name="Bad Co")

    def test_str_is_entity_name(self):
        assert str(make_institution(entity_name="XYZ Ltd")) == "XYZ Ltd"
