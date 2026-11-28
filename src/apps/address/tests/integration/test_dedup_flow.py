"""Deduplication: one row per distinct address (spec 0020 §7.4).

Addresses go in the way the product creates them — through
``Address.objects.get_or_create_address``, never ``objects.create`` — because
the manager is what normalizes, hashes and deduplicates (spec 0037 §3).
"""

import unicodedata

import pytest
from django.core.exceptions import ValidationError

from apps.address.models import EMPTY_ADDRESS_MESSAGE, Address
from apps.address.serializers import AddressSerializer

pytestmark = pytest.mark.django_db

FIELDS = {
    "line1": "12 MG Road",
    "city": "Bengaluru",
    "state": "Karnataka",
    "pincode": "560001",
    "district": "Bengaluru Urban",
    "police_station": "Cubbon Park",
}


@pytest.mark.scenario("ADDR-DEDUP-1")
def test_whitespace_variants_share_one_row(user):
    """'12  MG Road ' and '12 MG Road' are the same address."""
    first, created = Address.objects.get_or_create_address(
        created_by=user, **{**FIELDS, "line1": "12  MG Road "}
    )
    assert created

    second, created = Address.objects.get_or_create_address(created_by=user, **FIELDS)

    assert not created
    assert second.pk == first.pk
    assert Address.objects.count() == 1
    assert second.line1 == "12 MG Road"
    assert second.hash == first.hash


@pytest.mark.scenario("ADDR-DEDUP-2")
def test_malayalam_typed_with_different_input_methods_shares_one_row(user):
    """Precomposed and decomposed Unicode normalize to the same canonical form."""
    # The é gives the string a canonical decomposition; the Malayalam is the
    # text an input method would actually produce in either form.
    precomposed = unicodedata.normalize("NFC", "Alléവേഴം\u00e9 കേരളം")
    decomposed = unicodedata.normalize("NFD", precomposed)
    assert precomposed != decomposed  # the two byte strings really differ

    first, _ = Address.objects.get_or_create_address(
        created_by=user, **{**FIELDS, "line1": f"12 MG Road, {precomposed}"}
    )
    second, created = Address.objects.get_or_create_address(
        created_by=user, **{**FIELDS, "line1": f"12 MG Road, {decomposed}"}
    )

    assert not created
    assert second.pk == first.pk
    assert Address.objects.count() == 1


@pytest.mark.scenario("ADDR-DEDUP-3")
def test_a_pincode_keeps_no_spaces(user):
    """'560 001' is stored as '560001'."""
    address, _ = Address.objects.get_or_create_address(
        created_by=user, **{**FIELDS, "pincode": "560 001"}
    )

    assert address.pincode == "560001"


@pytest.mark.scenario("ADDR-DEDUP-4")
def test_case_is_significant(user):
    """'Bengaluru' and 'bengaluru' are two rows: a case-only correction must be saveable."""
    first, _ = Address.objects.get_or_create_address(created_by=user, **FIELDS)
    second, created = Address.objects.get_or_create_address(
        created_by=user, **{**FIELDS, "city": "bengaluru"}
    )

    assert created
    assert second.pk != first.pk
    assert Address.objects.count() == 2


@pytest.mark.scenario("ADDR-DEDUP-5")
def test_two_users_recording_the_same_address_share_one_row(make_user):
    """The shared row keeps the first recorder's created_by, and the API hides it."""
    first_user, second_user = make_user("first@example.com"), make_user("second@example.com")

    first, _ = Address.objects.get_or_create_address(created_by=first_user, **FIELDS)
    second, created = Address.objects.get_or_create_address(created_by=second_user, **FIELDS)

    assert not created
    assert second.pk == first.pk
    assert Address.objects.count() == 1
    assert second.created_by == first_user
    # created_by says who entered the address first, not who owns it: the
    # serializer other apps nest never exposes it.
    assert "created_by" not in AddressSerializer(second).data


@pytest.mark.scenario("ADDR-DEDUP-6")
def test_an_empty_address_is_refused(user):
    """Every field blank — or only invisible characters — is no address at all."""
    with pytest.raises(ValidationError) as excinfo:
        Address.objects.get_or_create_address(created_by=user)
    assert EMPTY_ADDRESS_MESSAGE in str(excinfo.value)

    with pytest.raises(ValidationError):
        Address.objects.get_or_create_address(
            created_by=user,
            line1="\u200b\ufeff",  # zero-width space + BOM
        )
    assert Address.objects.count() == 0


@pytest.mark.scenario("ADDR-DEDUP-7")
def test_a_partial_address_is_stored_and_reports_what_is_missing(user):
    """Only a pincode is enough while a filing is drafted; missing_fields lists the rest."""
    address, _ = Address.objects.get_or_create_address(created_by=user, pincode="560001")

    assert address.pincode == "560001"
    assert address.line1 == ""
    assert address.missing_fields == ["line1", "city", "state", "district"]

    # Completing it is a revision: a new row, the partial one untouched.
    completed = address.revise(created_by=user, line1="12 MG Road", city="Bengaluru")
    assert completed.pk != address.pk
    address.refresh_from_db()
    assert address.missing_fields == ["line1", "city", "state", "district"]


@pytest.mark.scenario("ADDR-DEDUP-8")
def test_invisible_characters_are_removed_but_joiners_are_kept(user):
    """ZWSP, word joiner and BOM carry no meaning; ZWJ/ZWNJ choose how letters join."""
    address, _ = Address.objects.get_or_create_address(
        created_by=user,
        # ZWSP (\u200b), word joiner (\u2060) and BOM (\ufeff) pasted in:
        **{**FIELDS, "line1": "12\u200b\u2060MG\ufeff Road"},
    )

    assert address.line1 == "12MG Road"

    with_joiner, _ = Address.objects.get_or_create_address(
        created_by=user,
        # A zero-width joiner (\u200d) and non-joiner (\u200c) inside the text:
        **{**FIELDS, "line1": "ക\u200dൊജി\u200c നഗർ"},
    )
    assert "\u200d" in with_joiner.line1  # kept
    assert "\u200c" in with_joiner.line1  # kept
