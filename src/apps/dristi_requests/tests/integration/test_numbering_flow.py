"""Request numbers follow the seeded tenant.state_code (spec 0010 §1.1).

The module seeds ``data/seed/core/configurations.toml`` once (the production
TOML must parse and resolve), so the app-wide ``state_code`` fixture is
shadowed here: the seeded row is committed, and a per-test row would clash
on the unique ``(config_set, config_key)``.
"""

import pytest
from django.urls import reverse

from apps.core.models import Configuration
from apps.dristi_requests.models import Request

from .conftest import CORE_SEED, read_seed_rows, submit

pytestmark = pytest.mark.django_db

SEEDED = read_seed_rows("core.Configuration", CORE_SEED)
STATE_CODE_ROW = next(
    row for row in SEEDED if row["config_set"] == "tenant" and row["config_key"] == "state_code"
)


@pytest.fixture(autouse=True)
def state_code():
    """The module seeds tenant/state_code once; the app-wide per-test row would clash."""
    return None


@pytest.mark.scenario("REQ-NUMBER-1")
def test_the_seeded_configuration_prefixes_the_first_request(
    auth_client, requester, approver_one, simple_type, admin_client, seeded_configuration
):
    """The production TOML seeds tenant.state_code=KL; the first request is KL-REQ-00001."""
    configured = Configuration.objects.get(config_set="tenant", config_key="state_code")
    assert configured.config_value == STATE_CODE_ROW["config_value"] == "KL"

    response = submit(auth_client(requester), simple_type, {"reason": "x"})
    assert response.status_code == 201, response.json()
    assert response.json()["request_number"] == "KL-REQ-00001"

    changelist = admin_client.get(
        reverse("admin:dristi_requests_request_changelist"), {"q": "KL-REQ-00001"}
    )
    assert changelist.status_code == 200
    assert "KL-REQ-00001" in changelist.content.decode()


@pytest.mark.scenario("REQ-NUMBER-2")
def test_a_resubmission_keeps_its_number(
    auth_client, requester, approver_one, simple_type, seeded_configuration
):
    """Reject then resubmit: only the version moves, the number is stable."""
    requester_client = auth_client(requester)
    created = submit(requester_client, simple_type, {"reason": "x"}).json()
    auth_client(approver_one).post(
        reverse("request-approval-decide", args=[created["approvals"][0]["id"]]),
        {"decision": "rejected", "comments": "no"},
        format="json",
    )

    body = requester_client.post(reverse("request-resubmit", args=[created["id"]])).json()
    assert body["request_number"] == created["request_number"]
    assert body["version"] == 2


@pytest.mark.scenario("REQ-NUMBER-3")
def test_editing_the_state_code_starts_a_new_series(
    auth_client, requester, approver_one, simple_type, admin_client, seeded_configuration
):
    """An operator edits tenant.state_code to BR: the next request is BR-REQ-00001."""
    client = auth_client(requester)
    first = submit(client, simple_type, {"reason": "one"}).json()
    second = submit(client, simple_type, {"reason": "two"}).json()
    assert first["request_number"] == "KL-REQ-00001"
    assert second["request_number"] == "KL-REQ-00002"

    configured = Configuration.objects.get(config_set="tenant", config_key="state_code")
    response = admin_client.post(
        reverse("admin:core_configuration_change", args=[configured.pk]),
        {
            "config_set": "tenant",
            "config_key": "state_code",
            "config_value": "BR",
            "description": configured.description or "",
            "is_active": "on",
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]

    third = submit(client, simple_type, {"reason": "three"})
    assert third.status_code == 201, third.json()
    assert third.json()["request_number"] == "BR-REQ-00001"

    # The existing numbers are untouched.
    numbers = set(
        Request.objects.filter(pk__in=[first["id"], second["id"]]).values_list(
            "request_number", flat=True
        )
    )
    assert numbers == {"KL-REQ-00001", "KL-REQ-00002"}


@pytest.mark.scenario("REQ-NUMBER-4")
def test_the_request_number_filter_is_exact_and_case_insensitive(
    auth_client, requester, approver_one, simple_type, seeded_configuration
):
    """?request_number=kl-req-00001 finds KL-REQ-00001, scoped to the caller's requests."""
    client = auth_client(requester)
    first = submit(client, simple_type, {"reason": "one"}).json()
    submit(client, simple_type, {"reason": "two"})

    body = client.get(reverse("request-list"), {"request_number": "kl-req-00001"}).json()
    assert [row["id"] for row in body["results"]] == [first["id"]]


@pytest.mark.scenario("REQ-NUMBER-5")
def test_the_approvals_queue_filters_by_request_number(
    auth_client, requester, approver_one, simple_type, seeded_configuration
):
    """The approver finds a request's approval by its number, scoped to their queue."""
    requester_client = auth_client(requester)
    submit(requester_client, simple_type, {"reason": "one"})
    second = submit(requester_client, simple_type, {"reason": "two"}).json()

    body = (
        auth_client(approver_one)
        .get(reverse("request-approval-list"), {"request_number": "KL-REQ-00002"})
        .json()
    )
    assert [row["request"] for row in body["results"]] == [second["id"]]
