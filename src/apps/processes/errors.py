"""Processes API error codes (domain 12, spec 0000 section 9, spec 0028 #11.7).

Codes are never renumbered. ``E12007``, ``E12008`` and ``E12010``–``E12012``
belong to signing and are defined with it.
"""

from apps.api.errors import define

# Lifecycle (#4); raised with what is wrong and the process's ``allowed_actions``.
INVALID_PROCESS_ACTION = define(
    "E12001", "This process cannot be changed this way in its current status.", status=409
)

# Starting processes from an order (#5.2); raised in-process to the orders module.
RECIPIENT_NOT_ALLOWED = define("E12002", "This process type cannot be addressed to this recipient.")
CHANNEL_NOT_ALLOWED = define(
    "E12003", "Choose a channel this process type may use in this deployment."
)
NO_DESTINATION = define(
    "E12004", "The recipient has no destination for this channel. Add one or choose another."
)
POLICE_STATION_REQUIRED = define(
    "E12005", "Choose a police station from the list for a police channel."
)
PARTY_TAKING_STEPS_REQUIRED = define(
    "E12006", "Choose the party directed to take steps for this recipient."
)
DESTINATION_INVALID = define(
    "E12017", "This is not a valid mobile number, email address or postal address."
)

# Steps (#7.1, #8)
NO_ENVELOPE_FOR_CHANNEL = define("E12009", "This process's channel takes no envelope.", status=409)
OUTCOME_RECORDED_BY_SYSTEM = define(
    "E12013",
    "The receiving system reports this channel's outcome; it cannot be recorded by hand.",
    status=409,
)
REASON_REQUIRED = define(
    "E12014", "Choose a reason from the list for a process that was not delivered or executed."
)
PROCESS_ACTION_NOT_ALLOWED = define(
    "E12015",
    "You are not allowed this step for this process's type and channel in this court.",
    status=403,
)
BULK_TOO_LARGE = define("E12016", "Too many processes in one request.")
OUTCOME_DATE_INVALID = define(
    "E12018", "The outcome date cannot be in the future or before the process was sent."
)
OUTCOME_FILE_INVALID = define(
    "E12019", "Upload the supporting file for this process first, then record the outcome."
)
