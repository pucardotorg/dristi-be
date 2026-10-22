"""Tests for the Person and Institution models (spec 0020 §2-3)."""

import datetime
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from apps.parties.models import Institution, Person, VerificationLevel, age_on, today_in_india
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

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_phone_number_is_stored_as_no_number(self, blank):
        person = Person(name="No Phone", phone_number=blank)

        person.full_clean()
        person.save()

        person.refresh_from_db()
        assert person.phone_number is None

    def test_blank_phone_number_is_accepted_without_full_clean(self):
        person = Person.objects.create(name="No Phone", phone_number="")

        assert Person.objects.get(pk=person.pk).phone_number is None

    def test_valid_indian_mobile_is_accepted(self):
        person = Person(name="Has Phone", phone_number="+919876543210")

        person.full_clean()

    @pytest.mark.parametrize(
        "number", ["+919876543210", "+14155552671", "+447911123456", "+6512345678"]
    )
    def test_phone_numbers_from_any_country_are_accepted(self, number):
        Person(name="Has Phone", phone_number=number).full_clean()

    @pytest.mark.parametrize(
        "number",
        [
            "9876543210",  # no country code
            "+0123456789",  # country codes do not start with 0
            "+91 98765 43210",  # stored without spaces
            "+91-9876543210",
            "+12345",  # too short
            "+1234567890123456",  # longer than E.164 allows
            "+91abc4567890",
        ],
    )
    def test_invalid_phone_number_fails_validation(self, number):
        person = Person(name="Bad Phone", phone_number=number)

        with pytest.raises(ValidationError) as exc:
            person.full_clean()

        assert "phone_number" in exc.value.message_dict

    def test_database_rejects_invalid_phone_number(self):
        person = make_person()

        with pytest.raises(IntegrityError), transaction.atomic():
            Person.objects.filter(pk=person.pk).update(phone_number="12345")

    def test_designation_without_institution_is_invalid(self):
        person = Person(name="Director", designation="Director")

        with pytest.raises(ValidationError) as exc:
            person.full_clean()

        assert "designation" in exc.value.message_dict

    def test_designation_with_institution_is_valid(self):
        person = Person(name="Director", designation="Director", institution=make_institution())

        person.full_clean()

    @pytest.mark.parametrize("relative_name", [None, "", "   "])
    def test_relation_needs_the_relatives_name(self, relative_name):
        person = Person(name="Ravi", relation="SON_OF", relative_name=relative_name)

        with pytest.raises(ValidationError) as exc:
            person.full_clean()

        assert "relative_name" in exc.value.message_dict

    def test_relation_with_the_relatives_name_is_valid(self):
        Person(name="Ravi", relation="SON_OF", relative_name="Mohan").full_clean()

    def test_no_relation_needs_no_relatives_name(self):
        Person(name="Ravi").full_clean()

    def test_designation_and_relation_errors_are_reported_together(self):
        person = Person(name="Ravi", designation="Director", relation="SON_OF")

        with pytest.raises(ValidationError) as exc:
            person.full_clean()

        assert {"designation", "relative_name"} <= set(exc.value.message_dict)

    def test_date_of_birth_in_the_future_is_rejected(self):
        tomorrow = today_in_india() + datetime.timedelta(days=1)

        with pytest.raises(ValidationError) as exc:
            Person(name="Ravi", date_of_birth=tomorrow).full_clean()

        assert "date_of_birth" in exc.value.message_dict

    def test_date_of_birth_today_or_earlier_is_valid(self):
        Person(name="Ravi", date_of_birth=today_in_india()).full_clean()
        Person(name="Ravi", date_of_birth=datetime.date(1980, 5, 17)).full_clean()

    def test_user_can_be_claimed_by_only_one_person(self):
        user = User.objects.create_user(mobile_number="+919876543210")
        make_person(user=user)

        with pytest.raises(ValidationError) as exc:
            make_person(name="Duplicate", user=user)

        assert "user" in exc.value.message_dict

    def test_database_rejects_unknown_verification_level(self):
        person = make_person()

        with pytest.raises(IntegrityError), transaction.atomic():
            Person.objects.filter(pk=person.pk).update(verification_level="GUESSED")

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

    @pytest.mark.parametrize(
        "number",
        [
            "08022334455",
            "080-22334455",
            "+91 80 2233 4455",
            "1800 123 4567",
            "+919876543210",
            "(080) 2233 4455",
            "(080)22334455",
            "+91 (80) 2233-4455",
        ],
    )
    def test_contact_number_accepts_phone_lines(self, number):
        institution = make_institution(contact_number=number)

        institution.full_clean()

    @pytest.mark.parametrize(
        "number",
        [
            "abc",
            "080-CALL-NOW",
            "080 2233 44x",
            "++91 80",
            "080--2233",
            "(080 2233",
            "080) 2233",
            "()",
            "(+91) 80",
        ],
    )
    def test_contact_number_rejects_letters_and_symbols(self, number):
        institution = Institution(
            entity_type="PRIVATE_LIMITED_COMPANY", entity_name="ABC", contact_number=number
        )

        with pytest.raises(ValidationError) as exc:
            institution.full_clean()

        assert "contact_number" in exc.value.message_dict

    def test_database_rejects_letters_in_contact_number(self):
        institution = make_institution()

        with pytest.raises(IntegrityError), transaction.atomic():
            Institution.objects.filter(pk=institution.pk).update(contact_number="abc")

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_contact_number_is_stored_as_no_number(self, blank):
        institution = make_institution(contact_number=blank)

        institution.full_clean()
        institution.save()

        institution.refresh_from_db()
        assert institution.contact_number is None

    def test_unknown_entity_type_fails_validation(self):
        institution = make_institution()
        institution.entity_type = "NOT_A_TYPE"

        with pytest.raises(ValidationError) as exc:
            institution.full_clean()

        assert "entity_type" in exc.value.message_dict

    def test_database_rejects_unknown_entity_type(self):
        institution = make_institution()

        with pytest.raises(IntegrityError), transaction.atomic():
            Institution.objects.filter(pk=institution.pk).update(entity_type="NOT_A_TYPE")

    def test_str_is_entity_name(self):
        assert str(make_institution(entity_name="XYZ Ltd")) == "XYZ Ltd"


@pytest.mark.django_db
class TestRulesOnEveryWrite:
    """``save()`` runs full validation, so no write path can skip a rule."""

    @pytest.mark.parametrize(
        "fields",
        [
            {"relation": "SON_OF"},  # relation without the relative's name
            {"date_of_birth": "2999-01-01"},
            {"designation": "Director"},  # designation without an institution
            {"phone_number": "12345"},
        ],
        ids=["relation", "date_of_birth", "designation", "phone_number"],
    )
    def test_plain_create_cannot_store_an_invalid_person(self, fields):
        with pytest.raises(ValidationError):
            Person.objects.create(name="Ravi", **fields)

        assert Person.objects.count() == 0

    def test_plain_create_cannot_store_an_invalid_institution(self):
        with pytest.raises(ValidationError):
            Institution.objects.create(entity_type="LLP", entity_name="X", contact_number="abc")

        assert Institution.objects.count() == 0

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_person_name_cannot_be_blank(self, blank):
        with pytest.raises(ValidationError) as exc:
            Person(name=blank).full_clean()

        assert "name" in exc.value.message_dict

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_institution_name_cannot_be_blank(self, blank):
        with pytest.raises(ValidationError) as exc:
            Institution(entity_type="LLP", entity_name=blank).full_clean()

        assert "entity_name" in exc.value.message_dict

    def test_names_are_stored_trimmed(self):
        person = make_person(name="  Ravi Kumar ")
        institution = make_institution(entity_name=" ABC Pvt Ltd  ")

        assert Person.objects.get(pk=person.pk).name == "Ravi Kumar"
        assert Institution.objects.get(pk=institution.pk).entity_name == "ABC Pvt Ltd"


@pytest.mark.django_db
class TestInstitutionAddress:
    def test_institution_has_a_registered_address(self):
        address = make_address()
        institution = make_institution(address=address)

        assert Institution.objects.get(pk=institution.pk).address == address

    def test_address_is_optional(self):
        assert make_institution().address is None

    def test_address_in_use_by_an_institution_cannot_be_deleted(self):
        address = make_address()
        make_institution(address=address)

        with pytest.raises(Exception):  # noqa: B017 - immutability or PROTECT, either blocks it
            address.delete()


@pytest.mark.django_db
class TestDisabilityStatus:
    def test_defaults_to_none(self):
        assert make_person().disability_status == "NONE"

    @pytest.mark.parametrize("missing", [None, "", "   "])
    def test_missing_value_is_stored_as_none(self, missing):
        person = make_person(disability_status=missing)

        assert Person.objects.get(pk=person.pk).disability_status == "NONE"

    def test_a_given_status_is_kept(self):
        person = make_person(disability_status="VISUAL")

        assert Person.objects.get(pk=person.pk).disability_status == "VISUAL"

    def test_unknown_status_is_rejected(self):
        with pytest.raises(ValidationError) as exc:
            Person(name="Ravi", disability_status="BLIND").full_clean()

        assert "disability_status" in exc.value.message_dict


class TestAgeOn:
    @pytest.mark.parametrize(
        ("born", "day", "age"),
        [
            (datetime.date(1980, 5, 17), datetime.date(2024, 5, 16), 43),  # day before
            (datetime.date(1980, 5, 17), datetime.date(2024, 5, 17), 44),  # birthday
            (datetime.date(1980, 5, 17), datetime.date(2024, 12, 31), 44),
            (datetime.date(2000, 2, 29), datetime.date(2023, 2, 28), 22),  # leap-day birth
            (datetime.date(2000, 2, 29), datetime.date(2023, 3, 1), 23),
            (datetime.date(2024, 1, 1), datetime.date(2024, 1, 1), 0),
        ],
    )
    def test_whole_years_on_a_day(self, born, day, age):
        assert age_on(born, day) == age


@pytest.mark.django_db
class TestAge:
    def test_age_is_optional(self):
        assert make_person().age is None

    def test_approximate_age_without_a_date_of_birth(self):
        person = make_person(age=45)

        assert Person.objects.get(pk=person.pk).age == 45

    @pytest.mark.parametrize("age", [-1, 151])
    def test_out_of_range_age_is_rejected(self, age):
        with pytest.raises(ValidationError) as exc:
            Person(name="Ravi", age=age).full_clean()

        assert "age" in exc.value.message_dict

    def test_date_of_birth_replaces_a_stated_age(self):
        person = make_person(date_of_birth=datetime.date(1980, 5, 17), age=30)

        assert Person.objects.get(pk=person.pk).age is None

    def test_contradicting_age_is_not_an_error_when_a_date_of_birth_is_given(self):
        # The date of birth wins; the stated age is dropped, not checked.
        Person(name="Ravi", date_of_birth=datetime.date(1980, 5, 17), age=99).full_clean()

    def test_current_age_comes_from_the_date_of_birth_when_known(self):
        born = datetime.date(1980, 5, 17)
        person = make_person(date_of_birth=born)

        assert person.current_age == age_on(born, today_in_india())

    def test_current_age_is_the_stated_age_without_a_date_of_birth(self):
        assert make_person(age=45).current_age == 45

    def test_person_stays_editable_after_their_birthday(self):
        # A person saved the day before their birthday, edited two days later.
        born = datetime.date(1980, 5, 17)
        with patch(
            "apps.parties.models.timezone.localdate", return_value=datetime.date(2024, 5, 16)
        ):
            person = make_person(date_of_birth=born, age=43)
            assert person.current_age == 43

        with patch(
            "apps.parties.models.timezone.localdate", return_value=datetime.date(2024, 5, 18)
        ):
            person.phone_number = "+919811111111"
            person.save()
            assert person.current_age == 44

        assert Person.objects.get(pk=person.pk).phone_number == "+919811111111"

    def test_database_rejects_an_impossible_age(self):
        person = make_person()

        with pytest.raises(IntegrityError), transaction.atomic():
            Person.objects.filter(pk=person.pk).update(age=200)


@pytest.mark.django_db
class TestTodayIsIndianDate:
    """``TIME_ZONE`` is UTC; dates of birth and ages must use India's date."""

    # 01:30 on 18 May in India is still 20:00 on 17 May in UTC.
    INDIA_EARLY_MORNING = datetime.datetime(2024, 5, 17, 20, 0, tzinfo=datetime.UTC)

    def test_someone_born_today_in_india_is_not_in_the_future(self):
        with patch.object(timezone, "now", return_value=self.INDIA_EARLY_MORNING):
            Person(name="Baby", date_of_birth=datetime.date(2024, 5, 18)).full_clean()

    def test_birthday_counts_from_midnight_in_india(self):
        with patch.object(timezone, "now", return_value=self.INDIA_EARLY_MORNING):
            person = Person(name="Ravi", date_of_birth=datetime.date(1980, 5, 18))

            assert person.current_age == 44


@pytest.mark.django_db
class TestHistory:
    """People and institutions change over a case, so every version is kept."""

    def test_editing_a_person_keeps_the_previous_values(self):
        person = make_person(name="Ravi Kumar", phone_number="+919876543210")

        person.name = "Ravi Kumar Sharma"
        person.save()

        versions = list(person.history.order_by("history_date"))
        assert [v.name for v in versions] == ["Ravi Kumar", "Ravi Kumar Sharma"]
        assert [v.history_type for v in versions] == ["+", "~"]

    def test_editing_an_institution_keeps_the_previous_values(self):
        institution = make_institution(entity_name="ABC Pvt Ltd")

        institution.entity_name = "ABC Private Limited"
        institution.save()

        names = list(
            institution.history.order_by("history_date").values_list("entity_name", flat=True)
        )
        assert names == ["ABC Pvt Ltd", "ABC Private Limited"]
