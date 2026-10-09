"""Post-approval hooks for the request types the users app owns.

Imported from ``UsersConfig.ready()`` so each hook registers exactly once.
"""

from apps.dristi_requests.hooks import register_hook
from apps.dristi_requests.models import RequestApproval

from .models import ApprovalStatus
from .verification import ADVOCATE_REGISTRATION, CLERK_REGISTRATION, VERIFICATIONS_BY_CODE


@register_hook(ADVOCATE_REGISTRATION)
@register_hook(CLERK_REGISTRATION)
def accept_registration(request):
    """Mark the requester's profile ACCEPTED once verification is approved.

    The change is attributed to the approver whose decision completed the
    request, not left on the registrant who last wrote the row.

    Idempotent, as hooks must be: approving again leaves it ACCEPTED.
    """
    verification = VERIFICATIONS_BY_CODE[request.request_type.code]
    profile = verification.profile_of(request.requester)
    profile.approval_status = ApprovalStatus.ACCEPTED
    profile.updated_by = _final_approver(request)
    profile.save(update_fields=["approval_status", "updated_by", "updated_at"])


def _final_approver(request):
    """Return the approver of the last approved step in the current round."""
    approval = (
        request.approvals.filter(version=request.version, status=RequestApproval.Status.APPROVED)
        .select_related("approver")
        .order_by("-step_order")
        .first()
    )
    return approval.approver if approval else None
