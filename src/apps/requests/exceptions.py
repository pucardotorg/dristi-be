"""Domain exceptions for the request workflow.

They subclass DRF exceptions so the default exception handler renders them
in the project's standard error format without extra wiring.
"""

from rest_framework import status
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

__all__ = [
    "InvalidRequestStateError",
    "InvalidApprovalStateError",
    "ApprovalRoutingError",
    "NotTheAssignedApproverError",
]


class InvalidRequestStateError(ValidationError):
    """Raised when an operation is not allowed for the request's current status."""

    default_detail = "The request is not in a state that allows this operation."


class InvalidApprovalStateError(ValidationError):
    """Raised when an approval has already been decided or is not actionable."""

    default_detail = "This approval is not pending and cannot be decided."


class ApprovalRoutingError(APIException):
    """Raised when no approver can be resolved for a required approval step."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "No approver could be resolved for the next approval step."
    default_code = "approval_routing_error"


class NotTheAssignedApproverError(PermissionDenied):
    """Raised when someone other than the assigned approver tries to decide."""

    default_detail = "Only the assigned approver can decide this approval."
