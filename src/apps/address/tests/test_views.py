"""Tests for GET /api/v1/pincodes/<pincode>/."""

from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.address.services import (
    PincodeDetails,
    PincodeNotFoundError,
    PincodeServiceUnavailableError,
)
from apps.users.models import RegistrationStatus, Role, User

LOOKUP = "apps.address.views.lookup_pincode"


@pytest.fixture(autouse=True)
def clear_cache():
    """Start every test with no cached lookups."""
    cache.clear()


@pytest.fixture
def client(db):
    """Return an API client signed in as a registered litigant."""
    user = User.objects.create_user(
        mobile_number="+919876543210",
        name="Priya",
        role=Role.LITIGANT,
        registration_status=RegistrationStatus.COMPLETE,
    )
    api_client = APIClient()
    api_client.force_authenticate(user)
    return api_client


def url(pincode):
    """Return the lookup URL for ``pincode``."""
    return reverse("pincode-lookup", kwargs={"pincode": pincode})


@pytest.mark.django_db
class TestPincodeLookupView:
    """Success, and a distinct status and code for each failure."""

    def test_returns_district_and_state(self, client):
        details = PincodeDetails(pincode="560001", district="Bangalore", state="Karnataka")
        with patch(LOOKUP, return_value=details):
            response = client.get(url("560001"))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["pincode"] == "560001"
        assert body["district"] == "Bangalore"
        assert body["state"] == "Karnataka"
        assert "meta" in body

    @pytest.mark.parametrize("pincode", ["012345", "56001", "5600011", "56000A"])
    def test_invalid_pincode_is_400_without_calling_india_post(self, client, pincode):
        with patch(LOOKUP) as lookup:
            response = client.get(url(pincode))

        lookup.assert_not_called()
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "invalid_pincode"

    def test_unknown_pincode_is_404(self, client):
        with patch(LOOKUP, side_effect=PincodeNotFoundError):
            response = client.get(url("999999"))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["code"] == "pincode_not_found"

    def test_india_post_down_is_503_with_a_clear_code(self, client):
        with patch(LOOKUP, side_effect=PincodeServiceUnavailableError):
            response = client.get(url("560001"))

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        body = response.json()
        assert body["code"] == "pincode_service_unavailable"
        assert "unavailable" in body["detail"]

    def test_requires_authentication(self):
        response = APIClient().get(url("560001"))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
