"""Payments API error codes (spec 0000 section 9, spec 0017 #12.5).

Domain ``06``. Provider exceptions are mapped onto these here, never in an
addon, so swapping the provider never changes the API's codes. What a payment
records in ``failure_code`` is a stored reason, not one of these.
"""

from apps.api.errors import define

DEMAND_NOT_PAYABLE = define("E06001", "This demand is already paid or cancelled.", status=409)
ITEM_NOT_PAYABLE = define("E06002", "This demand item is already paid or cancelled.", status=409)
ITEM_NOT_IN_DEMAND = define("E06003", "This demand item does not belong to the demand.")
DUPLICATE_DEMAND_ITEM = define("E06004", "The same demand item is listed more than once.")
PAYMENT_IN_FLIGHT = define(
    "E06005", "A payment for this demand item is already in progress.", status=409
)
CURRENCY_MISMATCH = define("E06006", "All demands paid together must share one currency.")
QUANTITY_BREAKDOWN_MISMATCH = define(
    "E06007", "The quantity breakdown does not multiply to the quantity."
)
DEMAND_TOTAL_ZERO = define("E06008", "A demand must total more than zero.")
CLIENT_REQUEST_ID_REUSED = define(
    "E06009",
    "This client_request_id was already used for a different payment.",
    status=409,
)
ITEM_NOT_CANCELLABLE = define(
    "E06010",
    "This demand item is paid or has a payment in progress and cannot be cancelled.",
    status=409,
)
PAYMENT_NOT_CANCELLABLE = define(
    "E06011", "This payment has already completed and cannot be cancelled.", status=409
)
PAYMENT_OUTCOME_PENDING = define(
    "E06012",
    "The payment provider may still complete this payment; it cannot be cancelled yet.",
    status=409,
)
PAYMENT_ALREADY_COMPLETED = define(
    "E06013", "The payment provider had already completed this payment.", status=409
)
PROVIDER_REJECTED = define(
    "E06014", "The payment provider refused to start this payment.", status=422
)
PROVIDER_UNAVAILABLE = define(
    "E06015", "The payment provider is temporarily unavailable.", status=503
)
PROVIDER_REPLAY_MISMATCH = define(
    "E06016",
    "The payment provider returned a different transaction for a repeated request.",
    status=409,
)
NOT_PAYMENT_CREATOR = define(
    "E06017", "Only the user who started a payment can cancel it.", status=403
)
BATCH_TOO_LARGE = define("E06018", "Too many demands in one batch.")
DEMAND_REPEATED_IN_BATCH = define("E06019", "A demand may appear only once in a batch.")
PROVIDER_OPTION_INVALID = define("E06020", "This payment option is not valid.")
# Not in the spec's table: cancelling a demand that is (partly) paid or has a
# payment in flight. Partly paid demands are wound down item by item instead.
DEMAND_NOT_CANCELLABLE = define(
    "E06021",
    "This demand is paid, partly paid or has a payment in progress and cannot be cancelled.",
    status=409,
)
# Not in the spec's original table: over REST only the user who raised a demand
# may cancel it or its items; raising modules cancel in-process (spec 0017 #13).
NOT_DEMAND_CREATOR = define(
    "E06022", "Only the user who raised this demand can cancel it.", status=403
)
