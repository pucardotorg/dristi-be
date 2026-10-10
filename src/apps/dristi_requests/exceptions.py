"""Domain exceptions for the request workflow.

They subclass DRF exceptions so the default exception handler renders them
in the project's standard error format without extra wiring. ``default_code``
is the registered error code (``apps.dristi_requests.errors``).
"""

from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from . import errors

__all__ = [
    "InvalidRequestStateError",
    "InvalidApprovalStateError",
    "ApprovalRoutingError",
    "NotTheAssignedApproverError",
]


class InvalidRequestStateError(ValidationError):
    """Raised when an operation is not allowed for the request's current status."""

    default_detail = errors.INVALID_REQUEST_STATE.msg
    default_code = errors.INVALID_REQUEST_STATE.code


class InvalidApprovalStateError(ValidationError):
    """Raised when an approval has already been decided or is not actionable."""

    default_detail = errors.INVALID_APPROVAL_STATE.msg
    default_code = errors.INVALID_APPROVAL_STATE.code


class ApprovalRoutingError(APIException):
    """Raised when no approver can be resolved for a required approval step."""

    status_code = errors.APPROVAL_ROUTING.status
    default_detail = errors.APPROVAL_ROUTING.msg
    default_code = errors.APPROVAL_ROUTING.code


class NotTheAssignedApproverError(PermissionDenied):
    """Raised when someone other than the assigned approver tries to decide."""

    default_detail = errors.NOT_THE_ASSIGNED_APPROVER.msg
    default_code = errors.NOT_THE_ASSIGNED_APPROVER.code
