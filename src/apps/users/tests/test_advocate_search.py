"""Tests for GET /advocates?search= (finding an advocate to add to a case, spec 0021 §4.4)."""

import itertools

import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from apps.users.models import AdvocateProfile, ApprovalStatus, RegistrationStatus, Role, User

pytestmark = pytest.mark.django_db

_numbers = itertools.count(1)


def make_user(registration_status=RegistrationStatus.COMPLETE, **fields):
    return User.objects.create_user(
        mobile_number=f"+91910000{next(_numbers):04d}",
        name=fields.pop("name", "Filer"),
        role=fields.pop("role", Role.LITIGANT),
        registration_status=registration_status,
        terms_version_accepted=settings.CURRENT_TERMS_VERSION,
        **fields,
    )


def make_advocate(name="Priya Sharma", bar="KA/1234/2020", status=ApprovalStatus.ACCEPTED):
    return AdvocateProfile.objects.create(
        user=make_user(role=Role.ADVOCATE, name=f"{name} (account)"),
        name=name,
        bar_registration_id=bar,
        approval_status=status,
    )


@pytest.fixture
def client():
    api = APIClient()
    api.force_authenticate(make_user())
    return api


def search(client, text):
    return client.get(reverse("advocate-create"), {"search": text})


def codes(response):
    return {error.get("field"): error["code"] for error in response.json()["errors"]}


class TestAdvocateSearch:
    def test_finds_by_name_or_bar_number_case_insensitively(self, client):
        priya = make_advocate()
        make_advocate(name="Ravi Menon", bar="KL/9876/2015")

        by_name = search(client, "priya").json()["results"]
        by_bar = search(client, "ka/1234").json()["results"]

        assert by_name == [
            {"id": str(priya.pk), "name": "Priya Sharma", "bar_registration_id": "KA/1234/2020"}
        ]
        assert [row["id"] for row in by_bar] == [str(priya.pk)]

    def test_only_approved_advocates_are_returned(self, client):
        make_advocate(name="Pending Advocate", bar="KA/1/2020", status=ApprovalStatus.PENDING)
        make_advocate(name="Rejected Advocate", bar="KA/2/2020", status=ApprovalStatus.REJECTED)
        approved = make_advocate(name="Approved Advocate", bar="KA/3/2020")

        rows = search(client, "advocate").json()["results"]

        assert [row["id"] for row in rows] == [str(approved.pk)]

    def test_falls_back_to_the_account_name(self, client):
        profile = make_advocate(name="")

        rows = search(client, "(account)").json()["results"]

        assert rows == [
            {
                "id": str(profile.pk),
                "name": profile.user.name,
                "bar_registration_id": profile.bar_registration_id,
            }
        ]

    @pytest.mark.parametrize("text", ["", "ab", "  a  "])
    def test_too_short_a_search_is_400(self, client, text):
        response = search(client, text)

        assert response.status_code == 400
        assert codes(response) == {"search": "E00007"}

    def test_needs_a_complete_registration(self):
        api = APIClient()
        api.force_authenticate(make_user(registration_status=RegistrationStatus.PENDING_PROFILE))

        assert search(api, "priya").status_code == 403

    def test_needs_a_login(self):
        assert search(APIClient(), "priya").status_code in (401, 403)

    def test_is_rate_limited(self, client, settings):
        settings.ADVOCATE_SEARCH_THROTTLE_RATE = "2/min"
        cache.clear()
        make_advocate()

        statuses = [search(client, "priya").status_code for _ in range(3)]

        assert statuses == [200, 200, 429]
