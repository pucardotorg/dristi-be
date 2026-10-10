"""Error codes for the request workflow (domain 02, spec 0000 section 9)."""

from apps.api.errors import define

INVALID_REQUEST_STATE = define(
    "E02001", "The request is not in a state that allows this operation."
)
INVALID_APPROVAL_STATE = define("E02002", "This approval is not pending and cannot be decided.")
APPROVAL_ROUTING = define(
    "E02003", "No approver could be resolved for the next approval step.", status=409
)
NOT_THE_ASSIGNED_APPROVER = define(
    "E02004", "Only the assigned approver can decide this approval.", status=403
)
DOCUMENT_TOO_LARGE = define("E02005", "This document is too large to download.", status=413)
INVALID_ATTRIBUTES = define("E02006", "The attributes do not match the request type's schema.")
INVALID_DOCUMENTS = define("E02007", "The attached documents are not acceptable.")
