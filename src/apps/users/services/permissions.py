"""Access gates.

Applied as DRF default permission classes so that forgetting to think about
access on a new endpoint fails closed. Endpoints that must be reachable earlier
opt out explicitly.
"""

from rest_framework.permissions import BasePermission

from ..models import ApprovalStatus
from ..verification import approval_status_of

from apps.users import errors


class IsAuthenticatedAndRegistered(BasePermission):
    """Allows only signed-in accounts that finished the registration wizard.

    Checks both halves, because a session issued part-way through registration
    is valid but gated: `POST /users/` sets a cookie before the wizard is done.
    """

    message = errors.REGISTRATION_INCOMPLETE.msg
    code = errors.REGISTRATION_INCOMPLETE.code

    def has_permission(self, request, view):
        """Return whether the caller is signed in and past the wizard."""
        user = request.user
        return bool(user and user.is_authenticated and user.is_registration_complete)


class IsNotAwaitingApproval(BasePermission):
    """Refuses an advocate or clerk whose registration is not approved.

    PENDING is waiting on the approver; REJECTED was refused and may only
    correct and resubmit. Accounts whose role is not verified (litigants,
    staff, approvers) and accounts without a profile yet pass: the latter are
    IsAuthenticatedAndRegistered's to gate.
    """

    message = "Account approval is pending or was not approved."

    def has_permission(self, request, view):
        """Return whether the caller is not held up by approval."""
        user = request.user
        if not (user and user.is_authenticated):
            return True
        return approval_status_of(user) not in (ApprovalStatus.PENDING, ApprovalStatus.REJECTED)


class IsRejectedRegistrant(BasePermission):
    """Allows only an advocate or clerk whose registration was not approved.

    Guards the endpoints that show the rejection and take the corrected
    registration; to anyone else there is nothing there to act on.
    """

    message = "There is no rejected registration to resubmit."

    def has_permission(self, request, view):
        """Return whether the caller's registration was rejected."""
        user = request.user
        return bool(
            user and user.is_authenticated and approval_status_of(user) == ApprovalStatus.REJECTED
        )


class HasAcceptedCurrentTerms(BasePermission):
    """Allows only accounts holding the terms version currently in force.

    Kept separate from IsAuthenticatedAndRegistered: the remedies differ — one
    sends the user to the wizard, the other to a re-acceptance screen.
    """

    message = errors.TERMS_NOT_CURRENT.msg
    code = errors.TERMS_NOT_CURRENT.code

    def has_permission(self, request, view):
        """Return whether the caller's accepted terms are current."""
        user = request.user
        return bool(user and user.is_authenticated and user.has_current_terms)
