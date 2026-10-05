"""Model-level tests for the request workflow."""

import pytest
from django.apps import apps
from django.contrib.auth.models import Group
from django.db import IntegrityError

from apps.dristi_requests.models import (
    ApprovalStep,
    Request,
    RequestApproval,
    RequestDocument,
    RequestType,
)


@pytest.mark.django_db
class TestRequestTypeModel:
    """Tests for RequestType."""

    def test_create_request_type(self):
        request_type = RequestType.objects.create(code="DEMO", name="Demo", min_documents=2)

        assert str(request_type) == "DEMO"
        assert request_type.is_active is True
        assert request_type.min_documents == 2
        assert request_type.schema == {}

    def test_code_is_unique(self):
        RequestType.objects.create(code="DEMO", name="Demo")

        with pytest.raises(IntegrityError):
            RequestType.objects.create(code="DEMO", name="Duplicate")

    def test_activatable_queryset(self):
        active = RequestType.objects.create(code="A", name="A")
        inactive = RequestType.objects.create(code="B", name="B", is_active=False)

        assert active in RequestType.objects.active()
        assert inactive not in RequestType.objects.active()


@pytest.mark.django_db
class TestApprovalStepModel:
    """Tests for ApprovalStep as a template."""

    def test_steps_related_to_type_and_ordered(self, two_step_type):
        orders = list(two_step_type.approval_steps.values_list("order", flat=True))

        assert orders == [0, 1]
        assert str(two_step_type.approval_steps.first()) == "TWO_STEP step 0"

    def test_order_unique_per_type(self, simple_type):
        with pytest.raises(IntegrityError):
            ApprovalStep.objects.create(
                request_type=simple_type, order=0, approver_role="LEVEL_ONE"
            )


@pytest.mark.django_db
class TestRequestModel:
    """Tests for Request and its relationships."""

    def test_defaults(self, simple_type, requester):
        request = Request.objects.create(request_type=simple_type, requester=requester)

        assert request.status == Request.Status.DRAFT
        assert request.version == 1
        assert request.current_step == 0
        assert request.is_open() is True
        assert request.current_approval is None
        assert list(requester.requests.all()) == [request]

    def test_documents_and_approvals_relationships(self, simple_type, requester, pdf_file):
        request = Request.objects.create(request_type=simple_type, requester=requester)
        document = RequestDocument.objects.create(
            request=request, file=pdf_file("a.pdf"), uploaded_by=requester
        )
        approval = RequestApproval.objects.create(request=request, approver=requester)

        assert list(request.documents.all()) == [document]
        assert list(request.approvals.all()) == [approval]
        assert document.filename == "a.pdf"
        assert approval.status == RequestApproval.Status.PENDING

    def test_current_approval_tracks_version(self, simple_type, requester, approver_one):
        request = Request.objects.create(
            request_type=simple_type, requester=requester, status=Request.Status.PENDING
        )
        RequestApproval.objects.create(
            request=request, approver=approver_one, version=1, step_order=0
        )

        assert request.current_approval.approver == approver_one

        request.version = 2
        assert request.current_approval is None

    def test_approval_unique_per_round_and_step(self, simple_type, requester, approver_one):
        request = Request.objects.create(request_type=simple_type, requester=requester)
        RequestApproval.objects.create(
            request=request, approver=approver_one, version=1, step_order=0
        )

        with pytest.raises(IntegrityError):
            RequestApproval.objects.create(
                request=request, approver=approver_one, version=1, step_order=0
            )


@pytest.mark.django_db
class TestModuleIsDomainAgnostic:
    """The app must not carry models for any specific request type."""

    def test_no_domain_specific_models(self):
        model_names = {
            model.__name__ for model in apps.get_app_config("dristi_requests").get_models()
        }

        assert model_names == {
            "RequestType",
            "ApprovalStep",
            "Request",
            "RequestDocument",
            "RequestApproval",
        }


@pytest.mark.django_db
class TestSeededConfiguration:
    """The LAWYER_BAR_UPDATE type is created by configuration (data migration)."""

    def test_lawyer_bar_update_type_is_seeded(self, lawyer_bar_type):
        assert lawyer_bar_type.min_documents == 1
        assert lawyer_bar_type.schema["required"] == ["name", "bar_number"]
        assert lawyer_bar_type.approval_steps.count() == 1
        assert lawyer_bar_type.approval_steps.first().approver_role == "BAR_ID_APPROVER"

    def test_seeded_step_points_at_the_bar_id_group(self, lawyer_bar_type):
        step = lawyer_bar_type.approval_steps.first()

        assert step.approver_group.name == "BAR_ID_APPROVER"
        assert not Group.objects.filter(name="BAR_COUNCIL_APPROVER").exists()
