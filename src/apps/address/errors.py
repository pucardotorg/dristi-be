"""Address API error codes (domain 05, spec 0000 section 9)."""

from apps.api.errors import define

INVALID_PINCODE = define("E05001", "Enter a valid 6-digit pincode not starting with 0.")
PINCODE_NOT_FOUND = define(
    "E05002", "No district or state is recorded for this pincode.", status=404
)
# India Post is down: the frontend should let the user type district and state.
PINCODE_SERVICE_UNAVAILABLE = define(
    "E05003",
    "The pincode lookup service is unavailable. Enter district and state manually.",
    status=503,
)
