"""Immutability and revision (spec 0020 §7.3).

A case file must forever show the address as it was when used: existing rows
are never rewritten or deleted, and editing means ``revise()`` — a new row
the caller repoints at.
"""

import pytest
from django.db import IntegrityError, transaction

from apps.address.models import Address, AddressImmutableError

pytestmark = pytest.mark.django_db

FIELDS = {
    "line1": "12 MG Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "pincode": "560001",
    "district": "Bengaluru Urban",
    "police_station": "Cubbon Park",
}


@pytest.mark.scenario("ADDR-IMMUTABLE-1")
def test_an_existing_address_cannot_be_saved(user):
    """Changing a field on the instance and saving raises; the row is untouched."""
    address, _ = Address.objects.get_or_create_address(created_by=user, **FIELDS)
    address.city = "Mysuru"

    with pytest.raises(AddressImmutableError):
        address.save()

    address.refresh_from_db()
    assert address.city == "Bengaluru"


@pytest.mark.scenario("ADDR-IMMUTABLE-2")
def test_an_address_cannot_be_deleted(user):
    """delete() raises; the row and its hash remain."""
    address, _ = Address.objects.get_or_create_address(created_by=user, **FIELDS)

    with pytest.raises(AddressImmutableError):
        address.delete()

    assert Address.objects.filter(pk=address.pk, hash=address.hash).exists()


@pytest.mark.scenario("ADDR-IMMUTABLE-3")
def test_revising_creates_a_new_row_and_leaves_the_original(user):
    """revise() returns a new address holding the revised values; the original is untouched."""
    original, _ = Address.objects.get_or_create_address(created_by=user, **FIELDS)

    revised = original.revise(created_by=user, city="Mysuru")

    assert revised.pk != original.pk
    assert revised.city == "Mysuru"
    assert revised.line1 == "12 MG Road"
    original.refresh_from_db()
    assert original.city == "Bengaluru"
    assert Address.objects.count() == 2


@pytest.mark.scenario("ADDR-IMMUTABLE-4")
def test_revising_deduplicates_and_a_no_change_revision_returns_self(user):
    """Revising toward an existing address returns it; revising nothing returns self."""
    original, _ = Address.objects.get_or_create_address(created_by=user, **FIELDS)
    other, _ = Address.objects.get_or_create_address(
        created_by=user, **{**FIELDS, "city": "Mysuru"}
    )

    revised = original.revise(created_by=user, city="Mysuru")
    assert revised.pk == other.pk
    assert Address.objects.count() == 2

    unchanged = original.revise(created_by=user)
    assert unchanged.pk == original.pk
    assert Address.objects.count() == 2


@pytest.mark.scenario("ADDR-IMMUTABLE-5")
def test_concurrent_recording_is_safe_because_the_hash_index_is_unique(user):
    """The unique hash index is what makes the losing concurrent insert fall back.

    A true two-thread race needs two connections (and PostgreSQL); the
    contract it exercises is pinned here instead: a direct duplicate insert
    is refused by the index, and get_or_create_address then returns the
    winner's row.
    """
    address, _ = Address.objects.get_or_create_address(created_by=user, **FIELDS)

    with pytest.raises(IntegrityError), transaction.atomic():
        Address(**{field: FIELDS[field] for field in Address.CONTENT_FIELDS}).save()

    again, created = Address.objects.get_or_create_address(created_by=user, **FIELDS)
    assert not created
    assert again.pk == address.pk
    assert Address.objects.count() == 1


@pytest.mark.scenario("ADDR-IMMUTABLE-6")
def test_bulk_create_normalizes_and_hashes(user):
    """bulk_create skips save(); the manager override still normalizes and hashes."""
    Address.objects.bulk_create(
        [
            Address(line1="  1 First Cross ", city="Bengaluru"),
            Address(line1="2 Second Cross", city="Bengaluru", pincode="560 002"),
        ]
    )

    first = Address.objects.get(line1="1 First Cross")
    assert first.hash  # normalized and hashed despite the skipped save()

    again, created = Address.objects.get_or_create_address(
        created_by=user, line1="1 First Cross", city="Bengaluru"
    )
    assert not created
    assert again.pk == first.pk

    assert Address.objects.get(pincode="560002").line1 == "2 Second Cross"
