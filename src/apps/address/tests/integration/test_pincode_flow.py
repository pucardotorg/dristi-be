"""Pincode pre-fill: what the address stores (spec 0020 §7.3, spec 0007 §7).

The locations side of the lookup (the ancestors call itself, its 404
contract) is pinned in the locations suite; these rows pin what the address
module does with the outcome: it stores what the client sends, denormalized,
and never looks the pincode up at save time.
"""

import pytest
from django.urls import reverse

from apps.address.models import Address

pytestmark = pytest.mark.django_db

PINCODE_CHAIN = {
    "country": "India",
    "state": "Kerala",
    "district": "Ernakulam",
    "pincode": "682001",
}


def ancestors(client, code, **params):
    """GET the ancestor chain of a location code; return the response."""
    return client.get(reverse("location-by-code-ancestors", args=[code]), params)


@pytest.mark.scenario("ADDR-PINCODE-1")
def test_the_prefill_lookup_result_is_denormalized_onto_the_row(client, user, seeded_locations):
    """The client resolves the pincode's ancestors; the address stores district/state as sent."""
    response = ancestors(client, "PIN_682001", is_active="true")

    assert response.status_code == 200
    chain = response.json()["data"]
    district = next(row["name"] for row in chain if row["location_type"] == "district")
    state = next(row["name"] for row in chain if row["location_type"] == "state")

    address, created = Address.objects.get_or_create_address(
        created_by=user,
        line1="12 Mahatma Gandhi Road",
        city="Kochi",
        pincode=PINCODE_CHAIN["pincode"],
        district=district,
        state=state,
    )

    assert created
    assert address.district == "Ernakulam"
    assert address.state == "Kerala"
    assert address.pincode == "682001"


@pytest.mark.scenario("ADDR-PINCODE-2")
def test_contradicting_district_and_state_are_stored_as_sent(user, seeded_locations):
    """No lookup or check happens at save time: the row holds what the client sent."""
    address, created = Address.objects.get_or_create_address(
        created_by=user,
        line1="12 Mahatma Gandhi Road",
        pincode="682001",
        district="Chennai",
        state="Tamil Nadu",  # contradicts the pincode's seeded chain
    )

    assert created
    assert address.district == "Chennai"
    assert address.state == "Tamil Nadu"


@pytest.mark.scenario("ADDR-PINCODE-3")
def test_an_unknown_pincode_means_manual_entry_not_a_block(client, user, seeded_locations):
    """The lookup 404s, the user types district and state by hand, the address is stored."""
    response = ancestors(client, "PIN_999999", is_active="true")
    assert response.status_code == 404

    address, created = Address.objects.get_or_create_address(
        created_by=user,
        line1="1 Some Road",
        pincode="999999",
        district="Aizawl",
        state="Mizoram",
    )

    assert created
    assert address.district == "Aizawl"
    assert address.state == "Mizoram"
