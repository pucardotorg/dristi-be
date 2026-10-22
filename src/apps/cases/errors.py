"""Case filing API error codes (domain 07, spec 0000 section 9)."""

from apps.api.errors import define

# Every write is refused once the case has left DRAFT_IN_PROGRESS (spec 0021 §7).
CASE_NOT_EDITABLE = define(
    "E07001", "This case has been submitted and can no longer be changed.", status=409
)
# A known document type, evidence type or details section that this case's type
# does not take; GET /case-types/{case_type} lists what it does.
NOT_ACCEPTED_FOR_CASE_TYPE = define("E07002", "Not accepted for this case type.")
# Evidence can only link to an active document of its own case.
DOCUMENT_NOT_ON_CASE = define("E07003", "No active document with this id on this case.")
