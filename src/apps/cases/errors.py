"""Case filing API error codes (domain 07, spec 0000 section 9, spec 0021)."""

from rest_framework.exceptions import ErrorDetail

from apps.api.errors import define


def coded(error, message=None):
    """Return one message carrying ``error``'s code, for a dict of field errors.

    For a ``ValidationError`` whose fields fail different rules, where
    ``ErrorCode.validation_error()`` would give every field the same code.
    """
    return ErrorDetail(message or error.message, code=error.code)


# Every write is refused once the case has left DRAFT_IN_PROGRESS (spec 0021 §7).
CASE_NOT_EDITABLE = define(
    "E07001", "This case has been submitted and can no longer be changed.", status=409
)
# A known document type, evidence type or details section that this case's type
# does not take; GET /case-types/{case_type} lists what it does.
NOT_ACCEPTED_FOR_CASE_TYPE = define("E07002", "Not accepted for this case type.")
# Evidence can only link to an active document of its own case.
DOCUMENT_NOT_ON_CASE = define("E07003", "No active document with this id on this case.")

# Lifecycle (spec 0021 §7)
INVALID_STATUS_TRANSITION = define(
    "E07004", "The case is not in a status this step can start from.", status=409
)
# Reported once per missing item, each on the part of the filing it concerns.
FILING_INCOMPLETE = define("E07005", "The filing is incomplete.")
SIGNATURES_PENDING = define("E07006", "Every complainant and POA holder must sign first.")

# Signing (spec 0021 §8)
ALREADY_SIGNED = define("E07007", "This participant has already signed.", status=409)
NOT_A_SIGNER = define("E07008", "Only complainants and POA holders sign the filing.")
SIGNATURE_NOT_FOUND = define(
    "E07009", "No completed e-signature of this case's filing produced this document."
)

# References within one case
# Also for a participant who has been removed: "Must be an active participant."
PARTICIPANT_NOT_ON_CASE = define("E07010", "Must be a participant of the same case.")
DUPLICATE_PARTICIPANT = define("E07011", "Each party may be listed only once.")

# Who may take part, and how (spec 0020 §4–6, spec 0021 §4)
INSTITUTION_NOT_ALLOWED = define(
    "E07012", "Only a complainant or an accused may be an institution."
)
# The message names the party and role: "This person is already a complainant …".
ROLE_ALREADY_HELD = define("E07013", "This party already holds this role on this case.")
BOTH_SIDES = define("E07014", "A party cannot be both a complainant and an accused on a case.")
CALLS_ACTIVE_WITNESS = define(
    "E07015", "Cannot be removed while an active witness is called by them."
)
# The message names the role needed: "Must be a POA holder." …
WRONG_ROLE = define("E07016", "Must be a complainant or an accused.")
WITNESS_ALREADY_CALLED = define("E07017", "This person is already a witness called by this party.")
SELF_REPRESENTATION = define("E07018", "A party cannot act for themselves.")
SELF_AS_ACCUSED = define("E07019", "You cannot name yourself as accused.")
ALREADY_ACTING = define("E07020", "This holder or advocate already acts for this party.")
ADVOCATE_NOT_APPROVED = define("E07021", "Must be an approved advocate.")
PARTY_IN_PERSON = define("E07022", "A party appearing in person cannot be given an advocate.")

# Request bodies
# The message names who the field is for: "Only for a witness." …
FIELD_NOT_APPLICABLE = define("E07023", "This field does not apply to this participant.")
FIELD_NOT_ACCEPTED = define("E07024", "This field is not accepted.")
PERSON_AND_SELF = define("E07025", "Send either person or self, not both.")

# Signing, continued (spec 0021 §8)
SIGNATURE_ALREADY_USED = define(
    "E07026", "This signed document is already recorded for another participant."
)
SIGNED_BY_SOMEONE_ELSE = define("E07027", "This document was e-signed by someone else.")
SIGNED_BEFORE_SUBMISSION = define(
    "E07028", "This document was e-signed before the case was submitted for signing."
)
