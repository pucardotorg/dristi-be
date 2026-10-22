"""Tests for GET /api/v1/pincodes/<pincode>/."""

from unittest.mock import patch

import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.address import errors
from apps.address.services import (
    PincodeDetails,
    PincodeNotFoundError,
    PincodeServiceUnavailableError,
)
from apps.users.models import RegistrationStatus, Role, User

LOOKUP = "apps.address.views.lookup_pincode"


def error_code(response):
    return response.json()["errors"][0]["code"]


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
        terms_version_accepted=settings.CURRENT_TERMS_VERSION,
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
        assert error_code(response) == errors.INVALID_PINCODE.code

    def test_unknown_pincode_is_404(self, client):
        with patch(LOOKUP, side_effect=PincodeNotFoundError):
            response = client.get(url("999999"))

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert error_code(response) == errors.PINCODE_NOT_FOUND.code

    def test_india_post_down_is_503_with_a_clear_code(self, client):
        with patch(LOOKUP, side_effect=PincodeServiceUnavailableError):
            response = client.get(url("560001"))

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert error_code(response) == errors.PINCODE_SERVICE_UNAVAILABLE.code

    def test_requires_authentication(self):
        response = APIClient().get(url("560001"))

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestApiStandards:
    """Spec 0000: the registration gate (§6) and the ``meta`` envelope (§8)."""

    def test_accounts_mid_registration_are_refused(self):
        user = User.objects.create_user(
            mobile_number="+919811111111",
            registration_status=RegistrationStatus.PENDING_PROFILE,
        )
        client = APIClient()
        client.force_authenticate(user)

        with patch(LOOKUP) as lookup:
            response = client.get(url("560001"))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        lookup.assert_not_called()

    def test_success_response_has_meta(self, client):
        details = PincodeDetails(pincode="560001", district="Bengaluru Urban", state="Karnataka")
        with patch(LOOKUP, return_value=details):
            body = client.get(url("560001")).json()

        assert set(body["meta"]) == {"timestamp", "app_version", "spec_version"}

    @pytest.mark.parametrize(
        ("pincode", "side_effect", "error"),
        [
            ("012345", None, errors.INVALID_PINCODE),
            ("560001", PincodeNotFoundError, errors.PINCODE_NOT_FOUND),
            ("560001", PincodeServiceUnavailableError, errors.PINCODE_SERVICE_UNAVAILABLE),
        ],
    )
    def test_error_responses_use_the_standard_shape(self, client, pincode, side_effect, error):
        with patch(LOOKUP, side_effect=side_effect):
            response = client.get(url(pincode))

        body = response.json()
        assert response.status_code == error.status
        assert set(body) == {"errors", "meta"}
        assert [item["code"] for item in body["errors"]] == [error.code]
