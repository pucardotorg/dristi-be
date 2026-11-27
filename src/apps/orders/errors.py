"""Orders API error codes (domain 14, spec 0000 section 9, spec 0039 #11.6).

Each default message reads on its own; services that know more (the status, the
reason, the documents) pass a fuller message with the same code.
"""

from apps.api.errors import define

INVALID_ORDER_ACTION = define(
    "E14001", "This order cannot be changed this way in its current status.", status=409
)
ORDER_STALE = define(
    "E14002",
    "Someone changed this order after you opened it. Reload it and try again.",
    status=412,
)
CASE_NOT_IN_COURTROOM = define(
    "E14003", "An order needs a case that is registered and has a courtroom.", status=409
)
HEARING_NOT_STARTED = define(
    "E14004", "An order can be drafted in a hearing only once the hearing has started.", status=409
)
ORDER_TEXT_EMPTY = define("E14005", "Write the order text before sending it for signing.")
NEXT_HEARING_NOT_SETTLED = define(
    "E14006",
    "Set the next hearing, or mark the case as not listed again, before sending for signing.",
    status=409,
)
ATTENDANCE_INCOMPLETE = define(
    "E14007", "Mark everyone's attendance before sending the order for signing.", status=409
)
ITEM_NOT_AVAILABLE = define(
    "E14008", "This order item is not available for this order.", status=409
)
ITEM_COMBINATION_NOT_ALLOWED = define(
    "E14009", "This order item cannot be combined with the items already on the order.", status=409
)
ITEM_TARGET_INVALID = define("E14010", "Choose the application this order item applies to.")
ITEM_VALUES_INVALID = define("E14011", "A value of this order item is not valid.")
MANDATORY_FIELDS_MISSING = define(
    "E14012",
    "Some order items still need answers before the order data can be completed.",
    status=409,
)
ORDER_DATA_COMPLETE = define(
    "E14013", "The order data is marked complete. Reopen it before changing it.", status=409
)
DIARY_ENTRY_LOCKED = define("E14014", "This diary entry can no longer be changed.", status=409)
SIGNATURE_NOT_VALID_FOR_ORDER = define(
    "E14015", "This signature does not belong to the order's current signing.", status=409
)
ORDER_ALREADY_SIGNED = define("E14016", "This order has already been signed.", status=409)
SIGNING_METHOD_NOT_ENABLED = define("E14017", "This signing method is not enabled for this court.")
SHORTCUT_NAME_TAKEN = define("E14018", "You already have a shortcut with this name.", status=409)
ROLE_REQUIRED = define(
    "E14019", "You do not hold the court role this action needs in this courtroom.", status=403
)
ORDER_TEXT_TOO_LARGE = define("E14020", "The order text is too large.")
DOCUMENT_NOT_ON_CASE = define("E14021", "This document is not in the case file.")
BULK_TOO_LARGE = define("E14022", "Too many orders for one bulk action.")
LINKS_NOT_ALLOWED_FOR_TYPE = define(
    "E14023", "Documents cannot be linked to an order of this type.", status=409
)
ORDER_TYPE_NOT_OFFERED = define("E14024", "This order type is not offered for this court.")
LINKED_DOCUMENTS_WOULD_BE_REMOVED = define(
    "E14025",
    "Changing to this type removes the documents linked to the order. Confirm to remove them.",
    status=409,
)
DIARY_ENTRY_IS_ORDER_TEXT = define(
    "E14026",
    "An order of this type has no separate diary entry: it is the order text.",
    status=409,
)
ORDER_TEXT_STRUCTURE_UNSUPPORTED = define(
    "E14027",
    "The signed PDF cannot show nested lists, lists and tables inside list items or table "
    "cells, or text inside a list or table outside its items and cells.",
)
ORDER_NOT_PRINTABLE = define(
    "E14028",
    "The order cannot be printed for signing. Shorten or simplify its text, then sign again.",
)
BULK_ACROSS_COURTROOMS = define("E14029", "Bulk order items apply to the orders of one courtroom.")
