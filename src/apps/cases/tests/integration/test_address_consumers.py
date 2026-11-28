"""How party writes use the address module (spec 0020 §4.6, §7).

These flows live in the cases suite because the party write is a cases
behavior (spec 0037 §2 rule 1); they pin the address module's consumer
contract and are tagged with the address scenario IDs.
"""

import pytest
from django.db.models import ProtectedError
from django.urls import reverse

from apps.address.models import Address, AddressImmutableError
from apps.cases.models import CaseContact, CaseType, ContactType
from apps.cases.services import services
from apps.parties.tests.factories import ADDRESS_DEFAULTS

pytestmark = pytest.mark.django_db

PERSON = {
    "name": "Rajesh Kumar",
    "date_of_birth": "1985-06-15",
    "gender": "MALE",
    "relation": "SON_OF",
    "relative_name": "Ram Kumar",
}


def add_complainant_with_address(client, case_id, address):
    """Add a complainant naming ``address``; return the response."""
    return client.post(
        reverse("case-complainant-list", args=[case_id]),
        {"person": PERSON, "addresses": [address], "mobile_numbers": ["+919876543210"]},
        format="json",
    )


@pytest.mark.scenario("ADDR-CONSUMERS-1")
def test_two_cases_naming_the_same_address_share_one_row(make_user, client_for):
    """A complainant and an accused at the same place share the row; neither owns it."""
    filer_a, filer_b = make_user(), make_user()
    case_a = services.start_draft(filer_a, CaseType.CHEQUE_BOUNCE)["draft_session_id"]
    case_b = services.start_draft(filer_b, CaseType.CHEQUE_BOUNCE)["draft_session_id"]

    before = Address.objects.count()
    response_a = add_complainant_with_address(client_for(filer_a), case_a, ADDRESS_DEFAULTS)
    response_b = add_complainant_with_address(
        client_for(filer_b), case_b, {**ADDRESS_DEFAULTS, "line1": "12  MG Road "}
    )

    assert response_a.status_code == 201, response_a.json()
    assert response_b.status_code == 201, response_b.json()
    assert Address.objects.count() == before + 1

    address = Address.objects.latest("created_at")
    contacts = CaseContact.objects.filter(contact_type=ContactType.ADDRESS, address=address)
    assert contacts.count() == 2
    assert {str(contact.case_id) for contact in contacts} == {
        response_a.json()["case_id"],
        response_b.json()["case_id"],
    }


@pytest.mark.scenario("ADDR-CONSUMERS-2")
def test_a_referenced_address_survives_every_delete_attempt(make_user, client_for):
    """Address.delete() always raises; the contact's PROTECT foreign key backs it up."""
    filer = make_user()
    case_id = services.start_draft(filer, CaseType.CHEQUE_BOUNCE)["draft_session_id"]
    response = add_complainant_with_address(client_for(filer), case_id, ADDRESS_DEFAULTS)
    assert response.status_code == 201, response.json()
    address = CaseContact.objects.get(
        case_id=response.json()["case_id"], contact_type=ContactType.ADDRESS
    ).address

    with pytest.raises(AddressImmutableError):
        address.delete()
    # A queryset delete bypasses the instance guard; the PROTECT FK catches it.
    with pytest.raises(ProtectedError):
        Address.objects.filter(pk=address.pk).delete()

    assert Address.objects.filter(pk=address.pk).exists()
