"""Service-layer tests: routing, decisions and lifecycle transitions."""

import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.dristi_requests import services
from apps.dristi_requests.conditions import evaluate_condition
from apps.dristi_requests.exceptions import ApprovalRoutingError
from apps.dristi_requests.models import ApprovalStep, Request, RequestApproval
from apps.dristi_requests.schema import SchemaValidationError, validate_against_schema
from apps.files.models import File


@pytest.mark.django_db
class TestSubmitAndFirstApproval:
    """Submission creates the first pending approval lazily."""

    def test_create_request_submits_and_routes(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "because"}
        )

        approval = request.current_approval
        assert request.status == Request.Status.PENDING
        assert approval is not None
        assert approval.approver == approver_one
        assert approval.step_order == 0
        assert approval.version == 1
        assert request.current_step == 0

    def test_documents_are_attached(self, simple_type, requester, approver_one, pdf_file):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file("one.pdf"), pdf_file("two.pdf")],
        )

        assert request.documents.count() == 2
        assert request.documents.first().file.user == requester

    def test_requester_is_never_their_own_approver(self, simple_type, make_user):
        requester = make_user("selfapprover@example.com", groups=["LEVEL_ONE"])
        other = make_user("other@example.com", groups=["LEVEL_ONE"])

        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        assert request.current_approval.approver == other

    def test_routing_error_when_no_candidate(self, simple_type, requester):
        with pytest.raises(ApprovalRoutingError):
            services.create_request(
                request_type=simple_type, requester=requester, data={"reason": "x"}
            )

        assert Request.objects.count() == 0

    def test_routing_error_when_step_misconfigured(self, simple_type, requester):
        simple_type.approval_steps.update(approver_role="")

        with pytest.raises(ApprovalRoutingError):
            services.create_request(
                request_type=simple_type, requester=requester, data={"reason": "x"}
            )

    def test_type_without_steps_is_approved_immediately(self, requester, simple_type):
        simple_type.approval_steps.all().delete()

        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        assert request.status == Request.Status.APPROVED

    def test_cannot_submit_twice(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        with pytest.raises(ValidationError):
            services.submit_request(request)

    def test_approver_group_takes_precedence(self, simple_type, requester, make_user):
        from django.contrib.auth.models import Group

        group = Group.objects.create(name="SPECIAL")
        special = make_user("special@example.com", groups=["SPECIAL"])
        make_user("level-one@example.com", groups=["LEVEL_ONE"])
        simple_type.approval_steps.update(approver_group=group)

        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        assert request.current_approval.approver == special


@pytest.mark.django_db
class TestDecide:
    """decide() drives the request through the approval chain."""

    def _submit(self, request_type, requester, data=None):
        return services.create_request(
            request_type=request_type, requester=requester, data=data or {}
        )

    def test_approve_moves_to_next_step(self, two_step_type, requester, approver_one, approver_two):
        request = self._submit(two_step_type, requester, {"amount": 10})
        first = request.current_approval

        services.decide(first, RequestApproval.Status.APPROVED, actor=approver_one, comments="ok")

        request.refresh_from_db()
        first.refresh_from_db()
        assert first.status == RequestApproval.Status.APPROVED
        assert first.comments == "ok"
        assert first.decided_at is not None
        assert request.status == Request.Status.PENDING
        assert request.current_step == 1
        assert request.current_approval.approver == approver_two

    def test_final_approval_marks_request_approved(self, simple_type, requester, approver_one):
        request = self._submit(simple_type, requester, {"reason": "x"})

        services.decide(request.current_approval, "approved", actor=approver_one)

        request.refresh_from_db()
        assert request.status == Request.Status.APPROVED
        assert request.current_approval is None

    def test_reject_closes_request(self, two_step_type, requester, approver_one, approver_two):
        request = self._submit(two_step_type, requester, {"amount": 10})

        services.decide(
            request.current_approval, "rejected", actor=approver_one, comments="missing docs"
        )

        request.refresh_from_db()
        assert request.status == Request.Status.REJECTED
        assert request.approvals.count() == 1
        assert request.approvals.first().comments == "missing docs"

    def test_only_assigned_approver_can_decide(
        self, simple_type, requester, approver_one, approver_two
    ):
        request = self._submit(simple_type, requester, {"reason": "x"})

        with pytest.raises(PermissionDenied):
            services.decide(request.current_approval, "approved", actor=approver_two)

        request.refresh_from_db()
        assert request.status == Request.Status.PENDING

    def test_requester_cannot_decide(self, simple_type, requester, approver_one):
        request = self._submit(simple_type, requester, {"reason": "x"})

        with pytest.raises(PermissionDenied):
            services.decide(request.current_approval, "approved", actor=requester)

    def test_completed_approval_cannot_be_decided_again(self, simple_type, requester, approver_one):
        request = self._submit(simple_type, requester, {"reason": "x"})
        approval = request.current_approval
        services.decide(approval, "approved", actor=approver_one)

        with pytest.raises(ValidationError):
            services.decide(approval, "rejected", actor=approver_one)

    def test_invalid_decision_value(self, simple_type, requester, approver_one):
        request = self._submit(simple_type, requester, {"reason": "x"})

        with pytest.raises(ValidationError):
            services.decide(request.current_approval, "skipped", actor=approver_one)

    def test_cancelled_request_cannot_be_approved(self, simple_type, requester, approver_one):
        request = self._submit(simple_type, requester, {"reason": "x"})
        approval = request.current_approval
        services.cancel(request)

        with pytest.raises(ValidationError):
            services.decide(approval, "approved", actor=approver_one)

    def test_only_current_step_can_be_acted_upon(
        self, two_step_type, requester, approver_one, approver_two
    ):
        request = self._submit(two_step_type, requester, {"amount": 5})
        stale = RequestApproval.objects.create(
            request=request,
            step_order=5,
            version=1,
            approver=approver_two,
            status=RequestApproval.Status.PENDING,
        )

        with pytest.raises(ValidationError):
            services.decide(stale, "approved", actor=approver_two)


@pytest.mark.django_db
class TestRoutingConditions:
    """Conditions are evaluated lazily per step against the request data."""

    def test_step_is_skipped_when_condition_not_met(
        self, two_step_type, requester, approver_one, approver_two
    ):
        two_step_type.approval_steps.filter(order=1).update(
            condition={"field": "data.amount", "op": "gt", "value": 1000}
        )

        request = services.create_request(
            request_type=two_step_type, requester=requester, data={"amount": 10}
        )
        services.decide(request.current_approval, "approved", actor=approver_one)

        request.refresh_from_db()
        assert request.status == Request.Status.APPROVED
        skipped = request.approvals.get(step_order=1)
        assert skipped.status == RequestApproval.Status.SKIPPED

    def test_step_is_used_when_condition_met(
        self, two_step_type, requester, approver_one, approver_two
    ):
        two_step_type.approval_steps.filter(order=1).update(
            condition={"field": "data.amount", "op": "gt", "value": 1000}
        )

        request = services.create_request(
            request_type=two_step_type, requester=requester, data={"amount": 5000}
        )
        services.decide(request.current_approval, "approved", actor=approver_one)

        request.refresh_from_db()
        assert request.status == Request.Status.PENDING
        assert request.current_approval.approver == approver_two

    def test_first_step_condition_can_skip_to_second(
        self, two_step_type, requester, approver_one, approver_two
    ):
        two_step_type.approval_steps.filter(order=0).update(
            condition={"field": "data.needs_level_one", "op": "eq", "value": True}
        )

        request = services.create_request(
            request_type=two_step_type, requester=requester, data={"amount": 1}
        )

        assert request.approvals.get(step_order=0).status == RequestApproval.Status.SKIPPED
        assert request.current_approval.approver == approver_two
        assert request.current_step == 1

    def test_condition_on_requester_group(self, simple_type, requester, approver_one):
        simple_type.approval_steps.update(
            condition={"field": "requester.groups", "op": "contains", "value": "VIP"}
        )

        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        assert request.status == Request.Status.APPROVED

    def test_condition_operators(self):
        context = {
            "data": {"amount": 100, "tags": ["a", "b"], "kind": "urgent"},
            "request_type": {"code": "SIMPLE"},
        }

        assert evaluate_condition({}, context) is True
        assert evaluate_condition(None, context) is True
        assert evaluate_condition({"field": "data.amount", "op": "gte", "value": 100}, context)
        assert evaluate_condition({"field": "data.amount", "op": "lt", "value": 101}, context)
        assert evaluate_condition(
            {"field": "data.kind", "op": "in", "value": ["urgent", "normal"]}, context
        )
        assert evaluate_condition({"field": "data.tags", "op": "contains", "value": "a"}, context)
        assert evaluate_condition(
            {"field": "data.missing", "op": "exists", "value": False}, context
        )
        assert not evaluate_condition({"field": "data.missing", "op": "eq", "value": 1}, context)
        assert evaluate_condition(
            {
                "all": [
                    {"field": "request_type.code", "op": "eq", "value": "SIMPLE"},
                    {"not": {"field": "data.amount", "op": "gt", "value": 1000}},
                ]
            },
            context,
        )
        assert evaluate_condition(
            {"any": [{"field": "data.kind", "op": "eq", "value": "nope"}, {}]}, context
        )


@pytest.mark.django_db
class TestResubmitAndCancel:
    """Resubmission and cancellation transitions."""

    def test_resubmit_starts_new_round(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "rejected", actor=approver_one, comments="no")

        services.resubmit(request, actor=requester)
        request.refresh_from_db()

        assert request.version == 2
        assert request.status == Request.Status.PENDING
        assert request.current_step == 0
        assert request.approvals.count() == 2
        new_approval = request.current_approval
        assert new_approval.version == 2
        assert new_approval.approver == approver_one

    def test_resubmitted_request_can_be_approved(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "rejected", actor=approver_one)
        services.resubmit(request)
        request.refresh_from_db()

        services.decide(request.current_approval, "approved", actor=approver_one)
        request.refresh_from_db()

        assert request.status == Request.Status.APPROVED

    def test_cannot_resubmit_pending_request(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        with pytest.raises(ValidationError):
            services.resubmit(request)

    def test_cannot_resubmit_cancelled_request(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.cancel(request)

        with pytest.raises(ValidationError):
            services.resubmit(request)

    def test_cancel_pending_skips_open_approvals(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        services.cancel(request, actor=requester)
        request.refresh_from_db()

        assert request.status == Request.Status.CANCELLED
        assert request.current_approval is None
        assert request.approvals.first().status == RequestApproval.Status.SKIPPED

    def test_cancel_rejected_request(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "rejected", actor=approver_one)

        services.cancel(request)
        request.refresh_from_db()

        assert request.status == Request.Status.CANCELLED

    def test_cannot_cancel_approved_request(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "approved", actor=approver_one)

        with pytest.raises(ValidationError):
            services.cancel(request)


@pytest.mark.django_db
class TestGetOrCreateNextStep:
    """The routing resolver is idempotent while an approval is pending."""

    def test_returns_existing_pending_approval(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )

        again = services.get_or_create_next_step(request)

        assert again == request.current_approval
        assert request.approvals.count() == 1

    def test_returns_none_when_no_steps_remain(self, simple_type, requester, approver_one):
        request = services.create_request(
            request_type=simple_type, requester=requester, data={"reason": "x"}
        )
        services.decide(request.current_approval, "approved", actor=approver_one)

        assert services.get_or_create_next_step(request) is None


@pytest.mark.django_db
class TestDocumentAuthorizationHelpers:
    """can_access_request / can_access_document rules."""

    def test_access_matrix(
        self, simple_type, requester, approver_one, approver_two, staff_user, outsider, pdf_file
    ):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file()],
        )
        document = request.documents.first()

        assert services.can_access_document(requester, document) is True
        assert services.can_access_document(approver_one, document) is True
        assert services.can_access_document(staff_user, document) is True
        assert services.can_access_document(approver_two, document) is False
        assert services.can_access_document(outsider, document) is False

    def test_approver_keeps_access_after_deciding(
        self, simple_type, requester, approver_one, pdf_file
    ):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file()],
        )
        services.decide(request.current_approval, "approved", actor=approver_one)

        assert services.can_access_document(approver_one, request.documents.first()) is True


class TestSchemaValidation:
    """Tests for the lightweight schema validator."""

    SCHEMA = {
        "type": "object",
        "required": ["name", "bar_number"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "bar_number": {"type": "string", "minLength": 1},
        },
    }

    def test_valid_payload(self):
        validate_against_schema(self.SCHEMA, {"name": "Jane", "bar_number": "KAR/1"})

    def test_missing_required_field(self):
        with pytest.raises(SchemaValidationError) as exc:
            validate_against_schema(self.SCHEMA, {"name": "Jane"})

        assert "'bar_number' is required" in str(exc.value)

    def test_wrong_type(self):
        with pytest.raises(SchemaValidationError):
            validate_against_schema(self.SCHEMA, {"name": 5, "bar_number": "x"})

    def test_min_length(self):
        with pytest.raises(SchemaValidationError):
            validate_against_schema(self.SCHEMA, {"name": "", "bar_number": "x"})

    def test_empty_schema_accepts_anything(self):
        validate_against_schema({}, {"anything": True})
        validate_against_schema(None, {"anything": True})

    def test_numeric_and_enum_constraints(self):
        schema = {
            "type": "object",
            "properties": {
                "amount": {"type": "number", "minimum": 1, "maximum": 10},
                "kind": {"enum": ["a", "b"]},
                "tags": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
            "additionalProperties": False,
        }

        validate_against_schema(schema, {"amount": 5, "kind": "a", "tags": ["x"]})

        with pytest.raises(SchemaValidationError):
            validate_against_schema(schema, {"amount": 50})
        with pytest.raises(SchemaValidationError):
            validate_against_schema(schema, {"kind": "z"})
        with pytest.raises(SchemaValidationError):
            validate_against_schema(schema, {"tags": [1]})
        with pytest.raises(SchemaValidationError):
            validate_against_schema(schema, {"unexpected": 1})


@pytest.mark.django_db
class TestDocumentModelStorage:
    """Documents are stored by apps.files, never directly by this app."""

    def test_document_references_an_apps_files_record(
        self, simple_type, requester, approver_one, pdf_file
    ):
        request = services.create_request(
            request_type=simple_type,
            requester=requester,
            data={"reason": "x"},
            files=[pdf_file("cert.pdf")],
        )
        document = request.documents.get()

        assert isinstance(document.file, File)
        assert document.filename == "cert.pdf"
        assert ApprovalStep.objects.filter(request_type=simple_type).exists()
