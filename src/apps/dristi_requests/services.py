"""Service layer for the generic request and approval workflow.

Views stay thin: all lifecycle transitions (submit, decide, resubmit,
cancel) and approval routing live here and run inside transactions so a
request is never left half-transitioned.
"""

import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from . import documents as request_documents
from .conditions import build_context, evaluate_condition
from .exceptions import (
    ApprovalRoutingError,
    InvalidApprovalStateError,
    InvalidRequestStateError,
    NotTheAssignedApproverError,
)
from .hooks import run_post_approval_hooks
from .models import Request, RequestApproval, RequestDocument

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Routing (lazy, per step)
# ---------------------------------------------------------------------------
def candidate_approvers(step, request):
    """Return the queryset of users eligible to approve ``step``.

    Roles are represented by auth groups in this project: ``approver_group``
    points at the group directly, ``approver_role`` names it. The requester
    is never eligible to approve their own request.
    """
    queryset = User.objects.filter(is_active=True)

    if step.approver_group_id:
        queryset = queryset.filter(groups=step.approver_group_id)
    elif step.approver_role:
        queryset = queryset.filter(groups__name=step.approver_role)
    else:
        raise ApprovalRoutingError(
            f"Approval step {step.order} of {step.request_type.code} has no "
            "approver_role or approver_group configured."
        )

    return queryset.exclude(pk=request.requester_id).order_by("mobile_number").distinct()


def resolve_approver(step, request):
    """Resolve the approver for ``step`` lazily, using the request's own data."""
    approver = candidate_approvers(step, request).first()
    if approver is None:
        raise ApprovalRoutingError(
            f"No eligible approver found for step {step.order} of {step.request_type.code}."
        )
    return approver


def _remaining_steps(request):
    """Return the template steps still to be considered for this round."""
    steps = request.request_type.approval_steps.all().order_by("order")
    decided_orders = request.approvals.filter(version=request.version).values_list(
        "step_order", flat=True
    )
    last_order = max(decided_orders, default=None)
    if last_order is not None:
        steps = steps.filter(order__gt=last_order)
    return steps


def get_or_create_next_step(request):
    """Return the pending approval for the request, creating it if needed.

    Steps whose ``condition`` does not match the request are recorded as
    ``skipped`` so the trail stays auditable. Returns ``None`` when no
    approval step remains, meaning the request is fully approved.
    """
    pending = request.current_approval
    if pending is not None:
        return pending

    context = build_context(request)
    for step in _remaining_steps(request):
        if not evaluate_condition(step.condition, context):
            RequestApproval.objects.create(
                request=request,
                step=step,
                step_order=step.order,
                version=request.version,
                status=RequestApproval.Status.SKIPPED,
                decided_at=timezone.now(),
                comments="Step condition not met.",
            )
            continue

        return RequestApproval.objects.create(
            request=request,
            step=step,
            step_order=step.order,
            version=request.version,
            approver=resolve_approver(step, request),
            status=RequestApproval.Status.PENDING,
        )

    return None


def create_first_approval_step(request):
    """Create the first pending approval for a freshly submitted request."""
    return get_or_create_next_step(request)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def create_request(*, request_type, requester, data, files=None, file_ids=None, submit=True):
    """Create a request (and its documents) and optionally submit it.

    ``files`` are uploads, stored here. ``file_ids`` are files the caller has
    already stored through ``apps.files`` (a registration document, say); they
    are only linked, and stay the caller's to clean up if this fails.

    Uploads are stored through ``apps.files`` *before* the request is
    created, outside the transaction, and deleted again if creating or
    submitting the request fails. The order matters: storage writes are not
    transactional, so the only way to undo them is to still hold the
    committed ``File`` rows when the request's transaction rolls back.
    """
    stored_ids = request_documents.store_documents(
        files or [], requester=requester, request_type=request_type
    )
    try:
        return _create_request(
            request_type=request_type,
            requester=requester,
            data=data,
            file_ids=[*(file_ids or []), *stored_ids],
            submit=submit,
        )
    except Exception:
        request_documents.discard_documents(stored_ids)
        raise


@transaction.atomic
def _create_request(*, request_type, requester, data, file_ids, submit):
    """Create the request and link its already-stored documents, atomically."""
    request = Request.objects.create(
        request_type=request_type,
        requester=requester,
        data=data,
        status=Request.Status.DRAFT,
    )
    # bulk_create bypasses save(), so the audit fields are set explicitly.
    RequestDocument.objects.bulk_create(
        [
            RequestDocument(
                request=request,
                file_id=file_id,
                created_by=requester,
                updated_by=requester,
            )
            for file_id in file_ids
        ]
    )
    if submit:
        submit_request(request)
    return request


@transaction.atomic
def submit_request(request):
    """Move a draft request into the pending state and route the first step."""
    if request.status != Request.Status.DRAFT:
        raise InvalidRequestStateError(
            f"Only draft requests can be submitted (current status: {request.status})."
        )

    request.status = Request.Status.PENDING
    request.current_step = 0
    request.save(update_fields=["status", "current_step", "updated_at"])

    approval = create_first_approval_step(request)
    if approval is None:
        _finalize_approved(request)
    else:
        request.current_step = approval.step_order
        request.save(update_fields=["current_step", "updated_at"])
    return request


def _finalize_approved(request):
    """Mark a request approved and run its post-approval hook."""
    request.status = Request.Status.APPROVED
    request.save(update_fields=["status", "updated_at"])
    run_post_approval_hooks(request)


@transaction.atomic
def decide(approval, decision, actor, comments=""):
    """Record an approver's decision and advance the request.

    The approval row and its request are locked for the duration of the
    transaction, so concurrent decisions cannot interleave and the hook runs
    in the same atomic block as the status change.
    """
    if decision not in RequestApproval.DECISIONS:
        raise InvalidApprovalStateError(
            f"Decision must be one of {', '.join(RequestApproval.DECISIONS)}."
        )

    approval = (
        RequestApproval.objects.select_for_update()
        .select_related("request", "request__request_type")
        .get(pk=approval.pk)
    )
    request = approval.request

    if approval.status != RequestApproval.Status.PENDING:
        raise InvalidApprovalStateError(
            f"Approval has already been {approval.status} and cannot be decided again."
        )
    if approval.approver_id != getattr(actor, "pk", None):
        raise NotTheAssignedApproverError()
    if request.status != Request.Status.PENDING:
        raise InvalidRequestStateError(
            f"The request is {request.status} and is no longer awaiting approval."
        )
    if approval.step_order != request.current_step or approval.version != request.version:
        raise InvalidApprovalStateError("Only the current approval step can be acted upon.")

    approval.status = decision
    approval.comments = comments or ""
    approval.decided_at = timezone.now()
    approval.save(update_fields=["status", "comments", "decided_at", "updated_at"])

    if decision == RequestApproval.Status.REJECTED:
        request.status = Request.Status.REJECTED
        request.save(update_fields=["status", "updated_at"])
        return approval

    next_approval = get_or_create_next_step(request)
    if next_approval is None:
        _finalize_approved(request)
    else:
        request.current_step = next_approval.step_order
        request.save(update_fields=["current_step", "updated_at"])
    return approval


@transaction.atomic
def resubmit(request, actor=None):
    """Resubmit a rejected request, starting a new approval round."""
    request = Request.objects.select_for_update().get(pk=request.pk)
    if request.status != Request.Status.REJECTED:
        raise InvalidRequestStateError(
            f"Only rejected requests can be resubmitted (current status: {request.status})."
        )

    request.version += 1
    request.status = Request.Status.PENDING
    request.current_step = 0
    request.save(update_fields=["version", "status", "current_step", "updated_at"])

    approval = create_first_approval_step(request)
    if approval is None:
        _finalize_approved(request)
    else:
        request.current_step = approval.step_order
        request.save(update_fields=["current_step", "updated_at"])
    return request


@transaction.atomic
def cancel(request, actor=None):
    """Cancel a draft, pending or rejected request."""
    request = Request.objects.select_for_update().get(pk=request.pk)
    if request.status not in (
        Request.Status.DRAFT,
        Request.Status.PENDING,
        Request.Status.REJECTED,
    ):
        raise InvalidRequestStateError(f"A {request.status} request cannot be cancelled.")

    request.approvals.filter(status=RequestApproval.Status.PENDING).update(
        status=RequestApproval.Status.SKIPPED,
        decided_at=timezone.now(),
        comments="Request cancelled by the requester.",
    )
    request.status = Request.Status.CANCELLED
    request.save(update_fields=["status", "updated_at"])
    return request


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------
def can_access_request(user, request):
    """Return ``True`` when ``user`` may view the request and its documents."""
    if not user or not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    if request.requester_id == user.pk:
        return True
    return request.approvals.filter(approver_id=user.pk).exists()


def can_access_document(user, document):
    """Return ``True`` when ``user`` may download the document."""
    return can_access_request(user, document.request)
