"""Tests for the immutable, deduplicated Address model (spec 0020 §7)."""

import unicodedata

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.address.models import Address, AddressImmutableError, address_hash, normalize_field
from apps.parties.tests.factories import ADDRESS_DEFAULTS, make_address
from apps.users.models import User


def make_user(mobile_number="+919876543210"):
    """Create a plain user account."""
    return User.objects.create_user(mobile_number=mobile_number)


class TestNormalization:
    """Canonical form used for storage and hashing."""

    def test_whitespace_is_trimmed_and_collapsed(self):
        assert normalize_field("line1", "  12   MG\tRoad ") == "12 MG Road"

    def test_pincode_loses_all_spaces(self):
        assert normalize_field("pincode", " 560 001 ") == "560001"

    def test_case_is_kept(self):
        assert normalize_field("city", "Bengaluru") == "Bengaluru"

    def test_unicode_is_stored_in_nfc_form(self):
        decomposed = unicodedata.normalize("NFD", "കൊച്ചി")

        assert normalize_field("city", decomposed) == unicodedata.normalize("NFC", "കൊച്ചി")

    def test_same_visible_text_hashes_alike_whatever_the_input_method(self):
        # "क़" typed as one precomposed character, and as "क" plus a nukta.
        precomposed = {**ADDRESS_DEFAULTS, "city": "\u0958"}
        decomposed = {**ADDRESS_DEFAULTS, "city": "\u0915\u093c"}

        assert address_hash(precomposed) == address_hash(decomposed)

    @pytest.mark.parametrize("invisible", ["\u200b", "\u2060", "\ufeff"])
    def test_invisible_characters_are_removed(self, invisible):
        assert normalize_field("line1", f"12 MG{invisible} Road") == "12 MG Road"

    @pytest.mark.parametrize("joiner", ["\u200c", "\u200d"])
    def test_joiners_are_kept_because_they_change_how_letters_join(self, joiner):
        text = f"ന{joiner}്"

        assert normalize_field("line1", text) == text

    def test_hash_ignores_spacing(self):
        messy = {**ADDRESS_DEFAULTS, "line1": "  12  MG   Road ", "pincode": "560 001"}

        assert address_hash(messy) == address_hash(ADDRESS_DEFAULTS)

    def test_hash_is_case_sensitive(self):
        lower = {**ADDRESS_DEFAULTS, "line1": "12 mg road"}

        assert address_hash(lower) != address_hash(ADDRESS_DEFAULTS)

    def test_hash_changes_with_any_content_field(self):
        base = address_hash(ADDRESS_DEFAULTS)

        for field in Address.CONTENT_FIELDS:
            changed = {**ADDRESS_DEFAULTS, field: ADDRESS_DEFAULTS[field] + "1"}
            assert address_hash(changed) != base, field

    def test_hash_does_not_merge_values_across_fields(self):
        a = {**ADDRESS_DEFAULTS, "line1": "12 MG", "city": "Road Bengaluru"}
        b = {**ADDRESS_DEFAULTS, "line1": "12 MG Road", "city": "Bengaluru"}

        assert address_hash(a) != address_hash(b)


@pytest.mark.django_db
class TestValidation:
    """Pincode and required-field validation."""

    @pytest.mark.parametrize("pincode", ["012345", "56001", "5600011", "56000A", ""])
    def test_invalid_pincode_is_rejected(self, pincode):
        with pytest.raises(ValidationError) as exc:
            make_address(pincode=pincode)

        assert "pincode" in exc.value.message_dict

    def test_pincode_with_a_space_is_accepted_and_stored_without_it(self):
        address = make_address(pincode="560 001")

        assert address.pincode == "560001"

    def test_missing_required_field_is_rejected(self):
        values = {k: v for k, v in ADDRESS_DEFAULTS.items() if k != "district"}

        with pytest.raises(ValidationError) as exc:
            Address.objects.get_or_create_address(**values)

        assert "district" in exc.value.message_dict

    def test_unknown_field_is_rejected(self):
        with pytest.raises(ValueError):
            Address.objects.get_or_create_address(**ADDRESS_DEFAULTS, country="India")

    def test_database_rejects_invalid_pincode(self):
        with pytest.raises(IntegrityError), transaction.atomic():
            Address.objects.create(**{**ADDRESS_DEFAULTS, "pincode": "012345"})


@pytest.mark.django_db
class TestDeduplication:
    """Identical addresses share one row (spec 0020 §7.4)."""

    def test_first_call_creates(self):
        _, created = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

        assert created is True

    def test_identical_address_reuses_the_row(self):
        first, _ = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)
        second, created = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

        assert created is False
        assert second.pk == first.pk
        assert Address.objects.count() == 1

    def test_spacing_differences_reuse_the_row(self):
        first = make_address()
        second = make_address(line1="12  MG Road ", city=" Bengaluru", pincode="560 001")

        assert second.pk == first.pk

    def test_case_differences_are_different_addresses(self):
        first = make_address(line1="12 mg road")
        second = make_address(line1="12 MG Road")

        assert second.pk != first.pk
        assert (first.line1, second.line1) == ("12 mg road", "12 MG Road")

    def test_different_police_station_is_a_different_address(self):
        first = make_address()
        second = make_address(police_station="Ulsoor")

        assert second.pk != first.pk

    def test_reuse_keeps_the_original_creator(self):
        creator = make_user("+919876543210")
        other = make_user("+919876543211")
        first, _ = Address.objects.get_or_create_address(created_by=creator, **ADDRESS_DEFAULTS)

        second, _ = Address.objects.get_or_create_address(created_by=other, **ADDRESS_DEFAULTS)

        assert second.pk == first.pk
        assert second.created_by == creator

    def test_stored_hash_matches_stored_values(self):
        address = make_address(line1="  12  MG Road ")

        assert address.line1 == "12 MG Road"
        assert address.hash == address_hash(ADDRESS_DEFAULTS)

    def test_save_recomputes_a_supplied_hash(self):
        address = Address(**ADDRESS_DEFAULTS, hash="not-a-real-hash")
        address.save()

        assert address.hash == address_hash(ADDRESS_DEFAULTS)

    def test_database_rejects_a_duplicate_insert(self):
        Address.objects.create(**ADDRESS_DEFAULTS)

        with pytest.raises(IntegrityError), transaction.atomic():
            Address.objects.create(**{**ADDRESS_DEFAULTS, "line1": "12  MG Road "})

    def test_validate_unique_rejects_a_duplicate(self):
        make_address()
        duplicate = Address(**{**ADDRESS_DEFAULTS, "city": "  Bengaluru "})

        with pytest.raises(ValidationError) as exc:
            duplicate.full_clean()

        assert "This address already exists." in str(exc.value)

    def test_validate_unique_accepts_a_new_address(self):
        make_address()

        Address(**{**ADDRESS_DEFAULTS, "line1": "99 Brigade Road"}).full_clean()

    @pytest.mark.parametrize("field", Address.CONTENT_FIELDS)
    @pytest.mark.parametrize("missing", [None, "", "   "])
    def test_full_clean_reports_a_missing_field_instead_of_crashing(self, field, missing):
        address = Address(**{**ADDRESS_DEFAULTS, field: missing})

        with pytest.raises(ValidationError) as exc:
            address.full_clean()

        assert field in exc.value.message_dict

    def test_validate_unique_skips_the_duplicate_check_while_a_field_is_missing(self):
        make_address()

        Address(**{**ADDRESS_DEFAULTS, "line1": None}).validate_unique()


@pytest.mark.django_db
class TestBulkCreate:
    """``bulk_create`` skips ``save()``; the manager hashes the rows itself."""

    def test_bulk_created_rows_are_normalized_and_hashed(self):
        Address.objects.bulk_create([Address(**{**ADDRESS_DEFAULTS, "line1": " 12  MG Road "})])

        stored = Address.objects.get()
        assert stored.line1 == "12 MG Road"
        assert stored.hash == address_hash(ADDRESS_DEFAULTS)

    def test_bulk_created_rows_deduplicate_with_saved_ones(self):
        Address.objects.bulk_create([Address(**ADDRESS_DEFAULTS)])

        _, created = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

        assert not created
        assert Address.objects.count() == 1

    def test_database_rejects_a_row_without_its_hash(self):
        make_address()

        with pytest.raises(IntegrityError), transaction.atomic():
            Address.objects.update(hash="")


@pytest.mark.django_db
class TestImmutability:
    """Rows are never updated or deleted in place."""

    def test_existing_address_cannot_be_saved(self):
        address = make_address()
        address.line1 = "Somewhere else"

        with pytest.raises(AddressImmutableError):
            address.save()

        address.refresh_from_db()
        assert address.line1 == ADDRESS_DEFAULTS["line1"]

    def test_refetched_address_cannot_be_saved(self):
        address = Address.objects.get(pk=make_address().pk)

        with pytest.raises(AddressImmutableError):
            address.save()

    def test_address_cannot_be_deleted(self):
        address = make_address()

        with pytest.raises(AddressImmutableError):
            address.delete()

        assert Address.objects.filter(pk=address.pk).exists()

    def test_creator_cannot_be_deleted_while_they_own_addresses(self):
        creator = make_user()
        Address.objects.get_or_create_address(created_by=creator, **ADDRESS_DEFAULTS)

        with pytest.raises(ProtectedError):
            creator.delete()


@pytest.mark.django_db
class TestRevise:
    """Editing produces a new row and leaves the old one untouched."""

    def test_revise_creates_a_new_row_and_leaves_the_old_one(self):
        original = make_address(line1="123 Main St")

        revised = original.revise(line1="45 New Rd")

        original.refresh_from_db()
        assert revised.pk != original.pk
        assert original.line1 == "123 Main St"
        assert revised.line1 == "45 New Rd"
        assert revised.pincode == original.pincode

    def test_revise_records_the_new_creator(self):
        user = make_user()

        revised = make_address().revise(created_by=user, line1="45 New Rd")

        assert revised.created_by == user

    def test_revise_without_changes_returns_the_same_row(self):
        original = make_address()

        assert original.revise().pk == original.pk

    def test_revise_can_correct_casing_only(self):
        original = make_address(city="bengaluru")

        corrected = original.revise(city="Bengaluru")

        assert corrected.pk != original.pk
        assert corrected.city == "Bengaluru"
        assert Address.objects.get(pk=original.pk).city == "bengaluru"

    def test_revise_to_an_existing_address_reuses_it(self):
        existing = make_address(line1="45 New Rd")
        original = make_address(line1="123 Main St")

        assert original.revise(line1="45  New Rd ").pk == existing.pk

    def test_revise_validates_the_new_values(self):
        with pytest.raises(ValidationError):
            make_address().revise(pincode="012345")

    def test_revise_rejects_non_content_fields(self):
        with pytest.raises(ValueError):
            make_address().revise(created_at=None)


@pytest.mark.django_db
def test_str_lists_the_address_parts():
    address = make_address()

    assert str(address) == "12 MG Road, Bengaluru, Bengaluru Urban, Karnataka - 560001"


@pytest.mark.django_db
def test_addresses_list_newest_first():
    older = make_address(line1="1 Old Road")
    newer = make_address(line1="2 New Road")

    assert list(Address.objects.all()) == [newer, older]
