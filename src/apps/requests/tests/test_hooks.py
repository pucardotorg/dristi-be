"""Tests for the post-approval hook registry.

The registry is the integration contract between this generic module and the
apps that consume it, so these tests exercise it the way a consuming app
would: register a hook for a request type code, submit through the generic
API, and assert the side effect ran once the last step was approved.
"""

import json

import pytest
from django.urls import reverse

from apps.requests import services
from apps.requests.hooks import (
    POST_APPROVAL_HOOKS,
    get_hook,
    register_hook,
    run_post_approval_hooks,
)
from apps.requests.models import Request


@pytest.fixture
def temporary_registry():
    """Restore the hook registry after each test that mutates it."""
    snapshot = dict(POST_APPROVAL_HOOKS)
    yield POST_APPROVAL_HOOKS
    POST_APPROVAL_HOOKS.clear()
    POST_APPROVAL_HOOKS.update(snapshot)


@pytest.mark.django_db
class TestHookRegistry:
    """register_hook / get_hook / run_post_approval_hooks."""

    def test_register_and_get_hook(self, temporary_registry):
        @register_hook("SIMPLE")
        def hook(request):  # pragma: no cover - replaced by assertions
            return request

        assert get_hook("SIMPLE") is hook

    def test_hook_runs_on_final_approval(
        self, temporary_registry, simple_type, requester, approver_one
    ):
        calls = []

        @register_hook("SIMPLE")
        def hook(request):
            calls.append(request.pk)

        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        assert calls == []

        services.decide(request.current_approval, "approved", actor=approver_one)

        assert calls == [request.pk]

    def test_hook_runs_only_after_the_last_step(
        self, temporary_registry, two_step_type, requester, approver_one, approver_two
    ):
        calls = []

        @register_hook("TWO_STEP")
        def hook(request):
            calls.append(request.pk)

        request = services.create_request(
            request_type=two_step_type, requester=requester, data={"amount": 1}
        )
        services.decide(request.current_approval, "approved", actor=approver_one)
        request.refresh_from_db()
        assert calls == []

        services.decide(request.current_approval, "approved", actor=approver_two)

        assert calls == [request.pk]

    def test_hook_does_not_run_on_rejection(
        self, temporary_registry, simple_type, requester, approver_one
    ):
        calls = []

        @register_hook("SIMPLE")
        def hook(request):
            calls.append(request.pk)

        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "rejected", actor=approver_one)

        assert calls == []

    def test_missing_hook_is_a_no_op(self, temporary_registry, simple_type, requester):
        POST_APPROVAL_HOOKS.pop("SIMPLE", None)
        request = Request.objects.create(request_type=simple_type, requester=requester)

        assert run_post_approval_hooks(request) is None

    def test_hook_failure_rolls_back_the_decision(
        self, temporary_registry, simple_type, requester, approver_one
    ):
        @register_hook("SIMPLE")
        def hook(request):
            raise RuntimeError("boom")

        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        approval = request.current_approval

        with pytest.raises(RuntimeError):
            services.decide(approval, "approved", actor=approver_one)

        request.refresh_from_db()
        approval.refresh_from_db()
        assert request.status == Request.Status.PENDING
        assert approval.status == "pending"


@pytest.mark.django_db
class TestConsumingAppIntegration:
    """How an external module (e.g. a user/profile app) plugs into the flow.

    Stands in for the real consumer: the hook reads ``data`` and the uploaded
    ``RequestDocument`` off the approved request and applies them to a model
    the requests app knows nothing about (here, the user itself).
    """

    def test_bar_id_flow_applies_side_effect_in_the_consuming_app(
        self, temporary_registry, auth_client, lawyer_bar_type, requester, bar_approver, pdf_file
    ):
        applied = {}

        @register_hook("LAWYER_BAR_UPDATE")
        def apply_bar_update(request):
            # A real consumer would update its own profile model here.
            document = request.documents.first()
            applied["user"] = request.requester
            applied["bar_number"] = request.data["bar_number"]
            applied["document_id"] = document.pk
            applied["filename"] = document.filename
            request.requester.first_name = request.data["name"]
            request.requester.save(update_fields=["first_name"])

        create_response = auth_client(requester).post(
            reverse("request-list"),
            {
                "request_type": "LAWYER_BAR_UPDATE",
                "attributes": json.dumps({"name": "Jane Doe", "bar_number": "KAR/1234/2019"}),
                "documents": [pdf_file()],
            },
            format="multipart",
        )
        assert create_response.status_code == 201

        request = Request.objects.get(pk=create_response.json()["id"])
        approval = request.current_approval
        assert approval.approver == bar_approver
        assert applied == {}

        decide_response = auth_client(bar_approver).post(
            reverse("request-approval-decide", args=[approval.pk]),
            {"decision": "approved", "comments": "Bar ID verified"},
            format="json",
        )
        assert decide_response.status_code == 200

        request.refresh_from_db()
        requester.refresh_from_db()
        assert request.status == Request.Status.APPROVED
        assert applied["user"] == requester
        assert applied["bar_number"] == "KAR/1234/2019"
        assert applied["document_id"] == request.documents.first().pk
        assert applied["filename"] == "bar-certificate.pdf"
        assert requester.first_name == "Jane Doe"

    def test_rejected_then_resubmitted_applies_once(
        self, temporary_registry, lawyer_bar_type, requester, bar_approver, pdf_file
    ):
        calls = []

        @register_hook("LAWYER_BAR_UPDATE")
        def apply_bar_update(request):
            calls.append(request.data["bar_number"])

        request = services.create_request(
            request_type=lawyer_bar_type,
            requester=requester,
            data={"name": "Jane", "bar_number": "KAR/1"},
            files=[pdf_file()],
        )
        services.decide(request.current_approval, "rejected", actor=bar_approver)
        assert calls == []

        services.resubmit(request)
        request.refresh_from_db()
        services.decide(request.current_approval, "approved", actor=bar_approver)

        assert calls == ["KAR/1"]

    def test_type_without_a_hook_just_gets_approved(
        self, temporary_registry, lawyer_bar_type, requester, bar_approver, pdf_file
    ):
        POST_APPROVAL_HOOKS.pop("LAWYER_BAR_UPDATE", None)

        request = services.create_request(
            request_type=lawyer_bar_type,
            requester=requester,
            data={"name": "Jane", "bar_number": "KAR/1"},
            files=[pdf_file()],
        )
        services.decide(request.current_approval, "approved", actor=bar_approver)

        request.refresh_from_db()
        assert request.status == Request.Status.APPROVED
