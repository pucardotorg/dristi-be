"""Hearings API error codes (domain 10, spec 0000 section 9, spec 0023 #10.6).

Each default message reads on its own; services that know more (the date, the
status, the counts) pass a fuller message with the same code.
"""

from apps.api.errors import define

# Lifecycle (#3, #6)
# Raised with the hearing's status and what it can be done instead; the error
# also carries ``allowed_actions``.
INVALID_TRANSITION = define(
    "E10001", "This hearing cannot be changed this way in its current status.", status=409
)
HEARING_STALE = define(
    "E10002",
    "Someone changed this hearing after you opened it. Reload it and try again.",
    status=412,
)

# Fixing a date (#4, #7)
# Raised with the reason, e.g. "it is not registered in a court".
CASE_NOT_LISTABLE = define("E10003", "This case cannot be listed for a hearing.", status=409)
CASE_ALREADY_SCHEDULED = define(
    "E10004", "This case already has a scheduled hearing; move that one instead.", status=409
)
DATE_IN_PAST = define("E10005", "The date is in the past. Choose today or a later date.")
DATE_NOT_SITTING = define("E10006", "The court does not sit on this date. Choose a sitting day.")
DATE_BEYOND_HORIZON = define("E10007", "The date is too far ahead. Choose an earlier date.")
DATE_NOT_AFTER_PREVIOUS = define("E10008", "The date must be after the previous hearing's date.")
COURT_DAY_FULL = define(
    "E10009", "The court's list for this date is full. Choose another date.", status=409
)
HEARING_NOT_TODAY = define(
    "E10010", "A hearing can be started only on the day it is listed for.", status=409
)

# Attendance (#6.5)
NOT_ON_ROLL = define(
    "E10011",
    "This person is not on the case's attendance roll. Only its complainants, accused, "
    "PoA holders and their advocates can be marked.",
)

# Moves (#8)
NOTHING_TO_CHANGE = define(
    "E10012", "The hearing is already listed for this date and purpose. Change one of them."
)
REASON_NEEDS_ORDER = define(
    "E10013",
    "A hearing can be moved for a party's application or on the court's own direction only "
    "through an order.",
)
PURPOSE_INACTIVE = define(
    "E10014", "This hearing purpose is retired or does not exist. Choose an active purpose."
)
PREVIEW_EXPIRED = define(
    "E10015", "This preview has expired. Preview the move again before confirming.", status=409
)
PREVIEW_ALREADY_CONFIRMED = define(
    "E10016", "This bulk move has already been confirmed.", status=409
)

# Calendar (#9.2)
# Raised with the counts of hearings and holds on the date.
DATE_HAS_HEARINGS = define(
    "E10017",
    "Hearings are listed or held on this date. Move them to another date first.",
    status=409,
)

# Access (#10.5)
NOT_COURT_STAFF = define("E10018", "Only staff of this court can do this.", status=403)

# Board (#5)
BOARD_MISMATCH = define(
    "E10019",
    "The new order must list every hearing waiting on that day's board, each exactly once.",
)

# In-process, surfaced by the orders module (#7.7)
HOLD_NOT_FOUND = define("E10020", "This order holds no next hearing date.", status=404)
# Raised with why it was released, e.g. "draft order discarded".
HOLD_RELEASED = define(
    "E10021", "The next hearing date this order held has been released.", status=409
)

# Raised with the specific reason: not started yet, or locked.
ATTENDANCE_LOCKED = define(
    "E10022",
    "Attendance can be marked only after the hearing has started and before its order "
    "is triggered.",
    status=409,
)
# Raised with each reason the date can no longer be confirmed.
HOLD_INVALID = define(
    "E10023", "The next hearing date in this order can no longer be confirmed.", status=409
)
BULK_TOO_LARGE = define("E10024", "Too many hearings for one bulk move.")
ROLE_REQUIRED = define(
    "E10025", "You do not hold the court role this action needs in this court.", status=403
)
