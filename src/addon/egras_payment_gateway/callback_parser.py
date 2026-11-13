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
from .config import EGRASKeyError, load_response_key
from .response_crypto import ResponseDecryptionError, checksum_matches, decrypt_pay_res
from .status_mapper import map_status_text

logger = logging.getLogger(constants.LOGGER_NAME)


def _lower_keyed(payload: Mapping[str, str]) -> dict[str, str]:
    """Match field names case-insensitively (``status``/``Status``)."""

    return {
        str(key).lower(): ("" if value is None else str(value)) for key, value in payload.items()
    }


def _decrypt_fields(pay_res: str, config) -> dict[str, str]:
    """Decrypt the ``payRes`` blob into the same lower-keyed fields (#5.4).

    A failure to decrypt (bad key, tampered blob, malformed JSON) is reported as
    a malformed callback: it cannot be correlated, so ``apps.payments`` redirects
    ``status=UNKNOWN`` and the poller resolves the payment through ``fetch_status``.
    """

    try:
        key = load_response_key(config.response_key_path, config.response_key_format)
        data = decrypt_pay_res(pay_res, key)
    except (ResponseDecryptionError, EGRASKeyError) as exc:
        logger.warning("event=%s reason=%s", constants.EGRAS_RESPONSE_DECRYPT_FAILED, exc)
        raise ProviderCallbackMalformed(
            constants.EGRAS_RESPONSE_DECRYPT_FAILED,
            "The encrypted e-GRAS callback could not be decrypted.",
        ) from exc

    # AES-GCM already authenticated the payload; the checksum is a redundant
    # extra check, logged but not enforced (and verification is the real gate).
    if not checksum_matches(data):
        logger.warning(
            "event=%s provider_payment_id=%s",
            constants.EGRAS_CHECKSUM_MISMATCH,
            str(data.get("Applicationnumber", "")),
        )
    return _lower_keyed(data)


def parse(payload: Mapping[str, str], config) -> ProviderCallback:
    """Parse an e-GRAS return-URL form into an untrusted ``ProviderCallback``.

    Handles both the encrypted ``payRes`` response (e-GRAS v3.7, #5.4) and the
    legacy plain-field response, so the cutover needs no flag.
    """

    fields = _lower_keyed(payload)
    pay_res = (fields.get(constants.CALLBACK_PAYRES, "") or "").strip()
    if pay_res:
        fields = _decrypt_fields(pay_res, config)

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
