"""Deciding approvals: multi-step routing, conditions and hooks (spec 0010 §4, §8, §9.2).

Each actor drives their own client; a client is never re-authenticated
mid-test (spec 0037 §4.1).
"""

import pytest
from django.urls import reverse

from apps.dristi_requests import hooks, services
from apps.dristi_requests.models import Request, RequestApproval

from .conftest import error_codes, submit

pytestmark = pytest.mark.django_db


def decide_url(approval_id):
    """Return the decide URL for an approval."""
    return reverse("request-approval-decide", args=[approval_id])


def trail(client, request_id):
    """Return the request's approval trail over the API (an unpaginated list)."""
    response = client.get(reverse("request-approvals", args=[request_id]))
    assert response.status_code == 200
    return response.json()["data"]


@pytest.mark.scenario("REQ-APPROVE-1")
def test_the_assigned_approver_sees_the_pending_step(
    auth_client, requester, approver_one, approver_two, two_step_type, pdf_file
):
    """Approver 1's queue holds step 0 with the request nested; approver 2's is empty."""
    submit(auth_client(requester), two_step_type, {"amount": 1500}, documents=[pdf_file()])

    queue = auth_client(approver_one).get(reverse("request-approval-list")).json()
    assert [row["step_order"] for row in queue["results"]] == [0]

    detail = (
        auth_client(approver_one)
        .get(reverse("request-approval-detail", args=[queue["results"][0]["id"]]))
        .json()
    )
    assert detail["request"]["data"] == {"amount": 1500}
    assert [d["filename"] for d in detail["request"]["documents"]] == ["bar-certificate.pdf"]

    other = auth_client(approver_two).get(reverse("request-approval-list")).json()
    assert other["results"] == []


@pytest.mark.scenario("REQ-APPROVE-2")
def test_two_steps_approve_in_sequence(
    auth_client, requester, approver_one, approver_two, two_step_type
):
    """Step 0 keeps the request pending at step 1; step 1 approves it; the trail records both."""
    requester_client = auth_client(requester)
    created = submit(requester_client, two_step_type, {"amount": 1500}).json()

    first = auth_client(approver_one).post(
        decide_url(created["approvals"][0]["id"]),
        {"decision": "approved", "comments": "papers in order"},
        format="json",
    )
    assert first.status_code == 200
    request = Request.objects.get(pk=created["id"])
    assert request.status == Request.Status.PENDING
    assert request.current_step == 1

    queue = auth_client(approver_two).get(reverse("request-approval-list")).json()
    assert [row["step_order"] for row in queue["results"]] == [1]

    second = auth_client(approver_two).post(
        decide_url(queue["results"][0]["id"]), {"decision": "approved"}, format="json"
    )
    assert second.status_code == 200
    request.refresh_from_db()
    assert request.status == Request.Status.APPROVED

    rows = trail(requester_client, created["id"])
    assert [(row["step_order"], row["status"]) for row in rows] == [
        (0, "approved"),
        (1, "approved"),
    ]
    assert rows[0]["comments"] == "papers in order"
    assert all(row["decided_at"] for row in rows)


@pytest.mark.scenario("REQ-APPROVE-3")
def test_a_step_whose_condition_misses_is_recorded_skipped(
    auth_client, requester, approver_one, conditional_type
):
    """amount 500 fails step 1's >1000 condition: the step is skipped and the request approved."""
    requester_client = auth_client(requester)
    created = submit(requester_client, conditional_type, {"amount": 500}).json()

    response = auth_client(approver_one).post(
        decide_url(created["approvals"][0]["id"]), {"decision": "approved"}, format="json"
    )
    assert response.status_code == 200

    request = Request.objects.get(pk=created["id"])
    assert request.status == Request.Status.APPROVED

    rows = trail(requester_client, created["id"])
    assert [(row["step_order"], row["status"]) for row in rows] == [
        (0, "approved"),
        (1, "skipped"),
    ]
    assert rows[1]["comments"] == "Step condition not met."


@pytest.mark.scenario("REQ-APPROVE-4")
def test_another_approver_cannot_decide(
    auth_client, requester, approver_one, approver_two, two_step_type
):
    """Someone else's approval is not in the caller's queue at all: a 404, not a 403."""
    created = submit(auth_client(requester), two_step_type, {"amount": 1500}).json()

    response = auth_client(approver_two).post(
        decide_url(created["approvals"][0]["id"]), {"decision": "approved"}, format="json"
    )

    assert response.status_code == 404
    assert Request.objects.get(pk=created["id"]).status == Request.Status.PENDING


@pytest.mark.scenario("REQ-APPROVE-5")
def test_the_requester_cannot_decide(auth_client, requester, approver_one, two_step_type):
    """The requester is never eligible to approve their own request: a 404."""
    created = submit(auth_client(requester), two_step_type, {"amount": 1500}).json()

    response = auth_client(requester).post(
        decide_url(created["approvals"][0]["id"]), {"decision": "approved"}, format="json"
    )

    assert response.status_code == 404


@pytest.mark.scenario("REQ-APPROVE-6")
def test_a_decided_step_leaves_the_pending_queue(
    auth_client, requester, approver_one, approver_two, two_step_type
):
    """After deciding, the approver's default queue empties; ?status=approved keeps the record."""
    created = submit(auth_client(requester), two_step_type, {"amount": 1500}).json()
    client = auth_client(approver_one)
    client.post(
        decide_url(created["approvals"][0]["id"]),
        {"decision": "approved", "comments": "fine"},
        format="json",
    )

    pending = client.get(reverse("request-approval-list")).json()
    assert pending["results"] == []

    history = client.get(reverse("request-approval-list"), {"status": "approved"}).json()
    assert [row["step_order"] for row in history["results"]] == [0]
    assert history["results"][0]["comments"] == "fine"
    assert history["results"][0]["decided_at"]


@pytest.mark.scenario("REQ-APPROVE-7")
def test_rejecting_requires_a_reason(auth_client, requester, approver_one, simple_type):
    """A rejection without comments is a 400 on comments (E00002)."""
    created = submit(auth_client(requester), simple_type, {"reason": "x"}).json()

    response = auth_client(approver_one).post(
        decide_url(created["approvals"][0]["id"]), {"decision": "rejected"}, format="json"
    )

    assert response.status_code == 400
    assert error_codes(response) == {"comments": ["E00002"]}
    assert Request.objects.get(pk=created["id"]).status == Request.Status.PENDING


@pytest.mark.scenario("REQ-APPROVE-8")
def test_an_approval_cannot_be_decided_twice(auth_client, requester, approver_one, simple_type):
    """Deciding an already-decided approval is a 400 (E02002)."""
    created = submit(auth_client(requester), simple_type, {"reason": "x"}).json()
    client = auth_client(approver_one)
    url = decide_url(created["approvals"][0]["id"])
    assert client.post(url, {"decision": "approved"}, format="json").status_code == 200

    response = client.post(url, {"decision": "approved"}, format="json")

    assert response.status_code == 400
    assert error_codes(response) == {None: ["E02002"]}


@pytest.mark.scenario("REQ-APPROVE-9")
def test_a_raising_hook_rolls_the_decision_back(auth_client, requester, approver_one, hook_type):
    """The hook runs in the deciding transaction; when it raises, nothing was decided."""
    seen = []

    @hooks.register_hook("HOOKED")
    def record(request):
        seen.append(request.pk)

    created = submit(auth_client(requester), hook_type, {"reason": "x"}).json()
    approval_id = created["approvals"][0]["id"]

    response = auth_client(approver_one).post(
        decide_url(approval_id), {"decision": "approved"}, format="json"
    )
    assert response.status_code == 200
    request = Request.objects.get(pk=created["id"])
    assert request.status == Request.Status.APPROVED
    assert seen == [request.pk]

    # A hook that raises takes the whole decision down with it.
    hooks.POST_APPROVAL_HOOKS.pop("HOOKED")
    seen.clear()

    @hooks.register_hook("HOOKED")
    def fail(request):
        raise RuntimeError("hook exploded")

    created = submit(auth_client(requester), hook_type, {"reason": "y"}).json()
    approval_id = created["approvals"][0]["id"]
    with pytest.raises(RuntimeError, match="hook exploded"):
        services.decide(RequestApproval.objects.get(pk=approval_id), "approved", actor=approver_one)

    assert RequestApproval.objects.get(pk=approval_id).status == RequestApproval.Status.PENDING
    assert Request.objects.get(pk=created["id"]).status == Request.Status.PENDING
    assert seen == []
