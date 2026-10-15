"""Spec 0000 conformance: auth gates, the ``meta`` envelope, pagination, error shape."""

import uuid

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.cases.models import Case, CaseType
from apps.users.models import RegistrationStatus, Role, User

pytestmark = pytest.mark.django_db

ANY_ID = uuid.uuid4()

# Every route in the app, with the methods it serves.
ENDPOINTS = [
    ("get", "case-type-list", []),
    ("get", "case-type-detail", ["CHEQUE_BOUNCE"]),
    ("get", "case-list", []),
    ("post", "case-list", []),
    ("get", "case-by-number", ["CC/1/2024"]),
    ("get", "case-document-list", [ANY_ID]),
    ("post", "case-document-list", [ANY_ID]),
    ("delete", "case-document-detail", [ANY_ID]),
    ("get", "case-details", [ANY_ID]),
    ("put", "case-details-section", [ANY_ID, "adr_other_prayer"]),
    ("get", "case-evidence-list", [ANY_ID]),
    ("post", "case-evidence-list", [ANY_ID]),
    ("patch", "case-evidence-detail", [ANY_ID]),
    ("delete", "case-evidence-detail", [ANY_ID]),
]


def call(client, method, name, args):
    return getattr(client, method)(reverse(name, args=args), {}, format="json")


@pytest.mark.parametrize(("method", "name", "args"), ENDPOINTS)
def test_anonymous_callers_are_refused(method, name, args):
    assert call(APIClient(), method, name, args).status_code in (401, 403)


@pytest.mark.parametrize(("method", "name", "args"), ENDPOINTS)
def test_accounts_mid_registration_are_refused(method, name, args):
    user = User.objects.create_user(
        mobile_number="+919811111111",
        name="Half registered",
        role=Role.LITIGANT,
        registration_status=RegistrationStatus.PENDING_PROFILE,
    )
    client = APIClient()
    client.force_authenticate(user)

    assert call(client, method, name, args).status_code == 403


class TestMetaEnvelope:
    def test_object_response_has_meta(self, client):
        body = client.post(reverse("case-list"), {"case_type": "CHEQUE_BOUNCE"}, format="json")

        assert set(body.json()["meta"]) == {"timestamp", "app_version", "spec_version"}

    def test_list_response_is_wrapped_in_data(self, client):
        body = client.get(reverse("case-type-list")).json()

        assert isinstance(body["data"], list)
        assert "meta" in body

    def test_paginated_response_keeps_pagination_keys(self, client):
        body = client.get(reverse("case-list")).json()

        assert {"count", "next", "previous", "results", "meta"} <= set(body)


class TestPagination:
    def test_cases_are_listed_twenty_per_page(self, client, user):
        for _ in range(21):
            Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=user)

        first = client.get(reverse("case-list")).json()
        second = client.get(first["next"]).json()

        assert first["count"] == 21
        assert len(first["results"]) == 20
        assert first["previous"] is None
        assert len(second["results"]) == 1
        assert second["next"] is None

    def test_filters_are_kept_in_page_links(self, client, user):
        for _ in range(21):
            Case.objects.create(case_type=CaseType.CHEQUE_BOUNCE, created_by=user)

        body = client.get(reverse("case-list"), {"status": "DRAFT_IN_PROGRESS"}).json()

        assert "status=DRAFT_IN_PROGRESS" in body["next"]


class TestErrorShape:
    """Every 400 reports a list of messages per field, as DRF serializers do."""

    @pytest.mark.parametrize(
        "params", [{"created_by": "someone"}, {"status": "NOPE"}], ids=["created_by", "status"]
    )
    def test_list_filter_errors_are_lists(self, client, params):
        body = client.get(reverse("case-list"), params).json()

        (field,) = params
        assert isinstance(body[field], list)

    def test_details_body_must_be_an_object(self, client, draft):
        response = client.put(
            reverse("case-details-section", args=[draft, "adr_other_prayer"]),
            ["not", "an", "object"],
            format="json",
        )

        assert response.status_code == 400
        assert response.json()["data"] == ["Expected a JSON object."]
        assert Case.objects.count() == 0
