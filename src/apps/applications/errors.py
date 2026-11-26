"""Applications API error codes (domain 13, spec 0000 section 9, spec 0033 #15.6).

Released codes never change meaning and are never reused, so the codes this
version no longer raises (``E13017``, ``E13018``, ``E13019``, ``E13021``) stay
defined. ``E13029`` is logged, never returned.
"""

from apps.api.errors import define

# Lifecycle (#5.3). Raised with the status and, in ``allowed_actions``, what can be done.
ACTION_NOT_ALLOWED = define(
    "E13001", "This application cannot be changed this way in its current status.", status=409
)
TYPE_NOT_AVAILABLE = define("E13002", "This type of application is not available to you here.")
CASE_NOT_ON_FILE = define(
    "E13003",
    "Applications can be raised only on a case registered in a court.",
    status=409,
)
CANNOT_DRAFT = define(
    "E13004", "You cannot draft applications for this case or this application.", status=403
)

# Fields every application carries (#3.3)
RAISED_BY_INVALID = define(
    "E13005",
    "Choose an advocate with vakalatnama access, or a party in person, on the application's side.",
)
LITIGANT_INVALID = define(
    "E13006", "Choose a litigant represented by the person the application is raised by."
)
DETAILS_REQUIRED = define("E13007", "Enter the application details.")
APPLICATION_INCOMPLETE = define("E13008", "This field is required to send the application.")
FIELD_NOT_FOR_TYPE = define("E13009", "This field does not apply to this application.")

# Documents (#6.4)
DOCUMENT_NOT_ACCEPTED = define("E13010", "This file is not an accepted document.")
DOCUMENT_NOT_ON_APPLICATION = define(
    "E13011", "This document is not attached to this field of the application."
)
DOCUMENT_IN_USE = define(
    "E13012", "This document is still used by the application. Clear the field first.", status=409
)

# Signing (#6.7)
NOT_THE_SIGNER = define(
    "E13013", "Only the person the application is raised by can sign it.", status=403
)
SIGNING_METHOD_NOT_ENABLED = define("E13014", "This signing method is not available.")
SIGNATURE_NOT_VALID = define(
    "E13015", "This signature cannot be recorded for this application.", status=409
)
HEARING_NOT_UPCOMING = define(
    "E13016",
    "The hearing this application is about has passed or is no longer the next hearing.",
    status=409,
)

# Not raised since PRD v41 (court acts are orders, #2.2, #8); kept so the numbers stay retired.
COURT_ACTION_REQUIRED = define(
    "E13017", "Court acts on an application are made by order.", status=403
)
DECISION_DATE_INVALID = define("E13018", "The decision date is not valid.")
DECISION_NOT_ON_DATE = define(
    "E13019", "The application is not listed for decision today.", status=409
)

# Objections (#9)
OBJECTION_NOT_ALLOWED = define(
    "E13020",
    "Only the other side can object to this application.",
    status=409,
)
OBJECTION_WINDOW_CLOSED = define(
    "E13021", "The time to object to this application has passed.", status=409
)
OBJECTION_TAKEN = define(
    "E13022", "An objection to this application has already been started.", status=409
)
TARGET_NOT_PENDING = define(
    "E13023",
    "The application objected to has already been decided, dismissed or expired.",
    status=409,
)

# Edit Litigant Details (#3.4, #3.5)
LITIGANT_NOT_EDITABLE = define("E13024", "You cannot edit this litigant's details.")
PHONE_IN_USE = define("E13025", "This phone number is already used by another person on the case.")

# Concurrency and numbering (#5.3, #7)
APPLICATION_STALE = define(
    "E13026",
    "Someone changed this application after you opened it. Reload it and try again.",
    status=412,
)
NUMBER_TAKEN = define(
    "E13027", "The application number was taken at the same moment. Try again.", status=409
)
NUMBERING_NOT_CONFIGURED = define(
    "E13028", "Application numbers are not configured for this state.", status=503
)
TYPE_WORKFLOW_FAILED = define(
    "E13029", "The application type's workflow failed after acceptance.", status=500
)
PAYMENT_IN_FLIGHT = define(
    "E13030",
    "A payment of this application's fee is in progress. Try again once it settles.",
    status=409,
)
