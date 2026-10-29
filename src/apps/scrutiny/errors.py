"""Scrutiny and registration error codes (domain 09, spec 0000 section 9, spec 0024 #8.5)."""

from apps.api.errors import define

# Rounds (#4)
ROUND_NOT_OPEN = define("E09001", "This case has no open round at this stage.", status=409)

# Flags (#3.2, #3.5)
FLAG_NOT_DRAFT = define("E09002", "Only a draft flag can be edited or withdrawn.", status=409)
# Reported on target_ref: an unknown field id or record index, section or document.
FLAG_TARGET_UNKNOWN = define("E09003", "This target is not on the case.")
# The screen's "No note — the advocate won't know what to fix".
FLAG_NOTE_REQUIRED = define(
    "E09004",
    "Add a note for the advocate; a document issue needs a reason or a note.",
)
FLAG_DUPLICATE = define("E09009", "This target already has a live flag in this round.", status=409)
# The synopsis and complaint are generated; flag the fields that render into them (DOC-01).
GENERATED_DOCUMENT_NOT_FLAGGABLE = define(
    "E09013", "A generated document cannot be flagged; flag its fields instead."
)
OATH_NOT_REQUIRED = define("E09016", "This state does not require an oath.")

# Decisions (#4.3, #4.4, #6)
NOTHING_TO_SEND_BACK = define("E09005", "Flag at least one item before sending the case back.")
# Raised with the number of unresolved flags in the message.
OPEN_ITEMS_NOT_ACKNOWLEDGED = define(
    "E09006", "The case has open items; acknowledge them to continue.", status=409
)
# Forward by someone who also registers, or Register at Scrutiny by someone who
# only scrutinises (SCR-11).
ACTION_NOT_FOR_ROLES = define(
    "E09007", "Your roles at this court call for the other action.", status=409
)
ROLE_REQUIRED = define("E09008", "You do not hold the court role this action needs.", status=403)
# A registration send back is one overall comment and no flags (REF-02).
SEND_BACK_COMMENT_REQUIRED = define(
    "E09010", "Give one overall comment; flags are not sent back from registration."
)
# Reported on courtroom_id: missing, or not a courtroom of the establishment (SCR-16).
COURTROOM_REQUIRED = define("E09017", "Choose a courtroom of this court establishment.")
# Reported on registration_type: missing where the state has several, or unknown (SCR-13).
REGISTRATION_TYPE_REQUIRED = define("E09018", "Choose one of this state's registration types.")

# Correction (#5)
EXPLANATION_REQUIRED = define("E09011", "An explanation needs a note.")
NOTHING_TO_RESUBMIT = define(
    "E09012", "Answer at least one item or make a change before resubmitting.", status=409
)

# Advisory checks (#2.4). Logged, never returned: a failure degrades the detail
# to one CHECKS_UNAVAILABLE alert instead of blocking the screen.
CHECKS_NOT_BOUND = define(
    "E09014", "No active checks rule is bound for this court establishment.", status=500
)
CHECKS_EVALUATION_FAILED = define(
    "E09015", "The checks rule failed or broke its contract.", status=500
)
