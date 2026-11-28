"""Seeded request types read back over the API (spec 0010 §5, spec 0037 §3).

The session seeds ``data/seed/core/dristi_requests/`` (it is part of the
migrated reference data), so these tests parse the same TOML back and check
the API serves it verbatim; the TOML stays the single source of truth.
"""

import json

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from .conftest import CORE_SEED, read_seed_rows

pytestmark = pytest.mark.django_db

SEEDED_TYPES = {
    row["code"]: row
    for row in read_seed_rows("dristi_requests.RequestType", CORE_SEED / "dristi_requests")
}
SEEDED_STEPS = read_seed_rows("dristi_requests.ApprovalStep", CORE_SEED / "dristi_requests")


@pytest.mark.scenario("REQ-TYPES-1")
def test_list_serves_the_seeded_types_verbatim(auth_client, requester):
    """The three seeded codes come back with name, min_documents and schema intact."""
    response = auth_client(requester).get(reverse("request-type-list"))

    assert response.status_code == 200
    body = response.json()
    assert {row["code"] for row in body["results"]} == set(SEEDED_TYPES)

    for row in body["results"]:
        seeded = SEEDED_TYPES[row["code"]]
        assert row["name"] == seeded["name"]
        assert row["min_documents"] == seeded["min_documents"]
        assert row["schema"] == seeded["schema"]

    # The seeded steps resolve their group reference to the BAR_ID_APPROVER group.
    assert Group.objects.filter(name="BAR_ID_APPROVER").exists()
    for row in body["results"]:
        seeded_steps = [s for s in SEEDED_STEPS if s["request_type"] == row["code"]]
        assert len(row["approval_steps"]) == len(seeded_steps)
        assert [s["approver_group"] for s in row["approval_steps"]] == [
            s["approver_group"] for s in seeded_steps
        ]


@pytest.mark.scenario("REQ-TYPES-2")
def test_retrieve_a_seeded_type(auth_client, requester, lawyer_bar_type):
    """LAWYER_BAR_UPDATE retrieves with its schema and document requirement."""
    response = auth_client(requester).get(
        reverse("request-type-detail", kwargs={"request_type_id": lawyer_bar_type.pk})
    )

    assert response.status_code == 200
    body = response.json()
    seeded = SEEDED_TYPES["LAWYER_BAR_UPDATE"]
    assert body["code"] == "LAWYER_BAR_UPDATE"
    assert body["min_documents"] == 1
    assert body["schema"] == seeded["schema"]
    assert body["schema"]["required"] == ["name", "bar_number"]


@pytest.mark.scenario("REQ-TYPES-3")
def test_deactivating_a_type_in_admin_removes_it(
    auth_client, requester, admin_client, lawyer_bar_type
):
    """An operator deactivates the type; the list and create both stop serving it."""
    change_url = reverse("admin:dristi_requests_requesttype_change", args=[lawyer_bar_type.pk])
    response = admin_client.post(
        change_url,
        {
            "code": lawyer_bar_type.code,
            "name": lawyer_bar_type.name,
            "description": lawyer_bar_type.description,
            "schema": json.dumps(lawyer_bar_type.schema),
            "min_documents": lawyer_bar_type.min_documents,
            # is_active left out: the checkbox is unchecked.
            "approval_steps-TOTAL_FORMS": 0,
            "approval_steps-INITIAL_FORMS": 0,
            "approval_steps-MIN_NUM_FORMS": 0,
            "approval_steps-MAX_NUM_FORMS": 1000,
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]

    client = auth_client(requester)
    body = client.get(reverse("request-type-list")).json()
    assert "LAWYER_BAR_UPDATE" not in {row["code"] for row in body["results"]}

    response = client.post(
        reverse("request-list"),
        {
            "request_type": "LAWYER_BAR_UPDATE",
            "attributes": json.dumps({"name": "A", "bar_number": "K/1/2020"}),
        },
        format="multipart",
    )
    assert response.status_code == 400
    assert {error["field"] for error in response.json()["errors"]} == {"request_type"}
