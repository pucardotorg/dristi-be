"""Return-URL callback parsing (spec 0022 #5).

e-GRAS auto-submits a browser form to the callback endpoint after the bank
returns. Nothing in it is signed, so ``trusted`` is **always** ``False``: the
payload is a hint that tells ``apps.payments`` *which* payment to verify, never
*what* happened. The authoritative outcome comes only from the server-to-server
GRN lookup (#6).
"""

import logging
from collections.abc import Mapping

from apps.payments.providers.base import (
    ProviderCallback,
    ProviderCallbackMalformed,
    ProviderOutcome,
    ProviderStatus,
)

from . import constants
from .status_mapper import map_status_text

logger = logging.getLogger(constants.LOGGER_NAME)


def _lower_keyed(payload: Mapping[str, str]) -> dict[str, str]:
    """Match field names case-insensitively (``status``/``Status``)."""

    return {str(key).lower(): value for key, value in payload.items()}


def parse(payload: Mapping[str, str], config) -> ProviderCallback:
    """Parse an e-GRAS return-URL form into an untrusted ``ProviderCallback``."""

    fields = _lower_keyed(payload)
    application_number = (fields.get(constants.CALLBACK_APPLICATION_NUMBER, "") or "").strip()

    if (
        not application_number
        or not application_number.startswith(config.application_prefix)
        or len(application_number) > constants.MAX_APPLICATION_NUMBER
    ):
        # An error-only callback (a status description with no application
        # number) cannot be correlated; apps.payments redirects with
        # status=UNKNOWN and its poller resolves the payment via fetch_status.
        raise ProviderCallbackMalformed(
            constants.EGRAS_CALLBACK_MALFORMED,
            "The e-GRAS callback carries no usable application number.",
        )

    status_text = (fields.get(constants.CALLBACK_STATUS, "") or "").strip()
    grn = (fields.get(constants.CALLBACK_GRN, "") or "").strip()
    outcome = map_status_text(status_text)
    failed = outcome == ProviderOutcome.FAILED

    hint = ProviderStatus(
        provider_payment_id=application_number,
        outcome=outcome,
        amount=None,
        provider_reference=grn,
        paid_at=None,
        failure_code=constants.EGRAS_PAYMENT_FAILED if failed else "",
        failure_message=constants.FAILURE_MESSAGE if failed else "",
        metadata={
            "cin": (fields.get(constants.CALLBACK_CIN, "") or "").strip(),
            "bankcode": (fields.get(constants.CALLBACK_BANKCODE, "") or "").strip(),
            "tdate": (fields.get(constants.CALLBACK_TDATE, "") or "").strip(),
            "egras_status": status_text,
        },
    )

    logger.info(
        "event=%s provider_payment_id=%s hinted_status=%r grn=%s",
        constants.EVENT_CALLBACK_RECEIVED,
        application_number,
        status_text,
        grn,
    )
    return ProviderCallback(status=hint, trusted=False)
