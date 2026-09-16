"""Tests for the post-approval hook registry and LAWYER_BAR_UPDATE."""

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
from apps.requests.models import LawyerBarDocument, LawyerProfile, Request
from apps.requests.request_types.lawyer_bar import (
    LAWYER_BAR_UPDATE_SCHEMA,
    REQUEST_TYPE_CODE,
    apply_bar_update,
    resolve_person_for_requester,
)


@pytest.fixture
def temporary_registry():
    """Restore the hook registry after each test that mutates it."""
    snapshot = dict(POST_APPROVAL_HOOKS)
    yield POST_APPROVAL_HOOKS
    POST_APPROVAL_HOOKS.clear()
    POST_APPROVAL_HOOKS.update(snapshot)


@pytest.mark.django_db
class TestHookRegistry:
    """register_hook / run_post_approval_hooks."""

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
class TestLawyerBarUpdate:
    """End-to-end behaviour of the first request type."""

    def test_schema_matches_configuration(self, lawyer_bar_type):
        assert lawyer_bar_type.schema == LAWYER_BAR_UPDATE_SCHEMA
        assert lawyer_bar_type.min_documents == 1
        assert get_hook(REQUEST_TYPE_CODE) is apply_bar_update

    def test_resolve_person_creates_profile(self, requester):
        person = resolve_person_for_requester(requester)

        assert person == LawyerProfile.objects.get(user=requester)
        assert resolve_person_for_requester(requester) == person

    def test_full_flow_applies_bar_update(
        self, auth_client, lawyer_bar_type, requester, bar_approver, pdf_file
    ):
        client = auth_client(requester)
        create_response = client.post(
            reverse("request-list"),
            {
                "request_type": REQUEST_TYPE_CODE,
                "attributes": json.dumps({"name": "Jane Doe", "bar_number": "KAR/1234/2019"}),
                "documents": [pdf_file()],
            },
            format="multipart",
        )
        assert create_response.status_code == 201

        request = Request.objects.get(pk=create_response.json()["id"])
        approval = request.current_approval
        assert approval.approver == bar_approver

        decide_response = auth_client(bar_approver).post(
            reverse("request-approval-decide", args=[approval.pk]),
            {"decision": "approved", "comments": "verified"},
            format="json",
        )
        assert decide_response.status_code == 200

        request.refresh_from_db()
        profile = LawyerProfile.objects.get(user=requester)
        bar_document = LawyerBarDocument.objects.get(person=profile)

        assert request.status == Request.Status.APPROVED
        assert profile.name == "Jane Doe"
        assert profile.bar_number == "KAR/1234/2019"
        assert bar_document.request_document == request.documents.first()

    def test_rejected_then_resubmitted_applies_once(
        self, lawyer_bar_type, requester, bar_approver, pdf_file
    ):
        request = services.create_request(
            request_type=lawyer_bar_type,
            requester=requester,
            data={"name": "Jane", "bar_number": "KAR/1"},
            files=[pdf_file()],
        )
        services.decide(request.current_approval, "rejected", actor=bar_approver)
        assert not LawyerProfile.objects.filter(user=requester).exists()

        services.resubmit(request)
        request.refresh_from_db()
        services.decide(request.current_approval, "approved", actor=bar_approver)

        assert LawyerBarDocument.objects.filter(person__user=requester).count() == 1
