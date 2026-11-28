"""The address admin: add and view only (spec 0020 §7.3; spec 0037 §5).

Every beat goes through the real admin views as a logged-in superuser —
adding works and stamps the creator, editing and deleting are refused, and a
duplicate is a form error rather than a 500 from the unique index.
"""

import pytest
from django.urls import reverse

from apps.address.models import Address
from apps.parties.tests.factories import ADDRESS_DEFAULTS

pytestmark = pytest.mark.django_db


@pytest.mark.scenario("ADDR-ADMIN-1")
def test_an_operator_adds_an_address(admin_client):
    """The add form saves the address normalized and hashed, creator stamped."""
    response = admin_client.post(reverse("admin:address_address_add"), ADDRESS_DEFAULTS)

    assert response.status_code == 302, response.content.decode()[:2000]
    address = Address.objects.get()
    assert address.line1 == "12 MG Road"  # stored normalized
    assert address.hash
    assert address.created_by == admin_client.user


@pytest.mark.scenario("ADDR-ADMIN-2")
def test_adding_a_duplicate_is_a_form_error_not_a_500(admin_client):
    """'This address already exists.' from model validation, not the unique index."""
    Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

    response = admin_client.post(
        reverse("admin:address_address_add"), {**ADDRESS_DEFAULTS, "line1": "12  MG Road "}
    )

    assert response.status_code == 200
    assert "This address already exists." in response.content.decode()
    assert Address.objects.count() == 1


@pytest.mark.scenario("ADDR-ADMIN-3")
def test_an_existing_address_cannot_be_changed_through_the_admin(admin_client):
    """The change view refuses the POST and the row stays untouched."""
    address, _ = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

    response = admin_client.post(
        reverse("admin:address_address_change", args=[address.pk]),
        {**ADDRESS_DEFAULTS, "city": "Mysuru"},
    )

    assert response.status_code == 403
    address.refresh_from_db()
    assert address.city == "Bengaluru"


@pytest.mark.scenario("ADDR-ADMIN-4")
def test_an_address_cannot_be_deleted_through_the_admin(admin_client):
    """The delete view refuses; the row remains."""
    address, _ = Address.objects.get_or_create_address(**ADDRESS_DEFAULTS)

    response = admin_client.post(reverse("admin:address_address_delete", args=[address.pk]))

    assert response.status_code == 403
    assert Address.objects.filter(pk=address.pk).exists()


@pytest.mark.scenario("ADDR-ADMIN-5")
def test_an_invalid_pincode_is_a_field_error(admin_client):
    """A pincode is 6 digits not starting with 0, or blank."""
    for bad in ("012345", "12345"):
        response = admin_client.post(
            reverse("admin:address_address_add"), {**ADDRESS_DEFAULTS, "pincode": bad}
        )
        assert response.status_code == 200
        assert "Enter a valid 6-digit pincode not starting with 0." in response.content.decode()

    assert Address.objects.count() == 0
