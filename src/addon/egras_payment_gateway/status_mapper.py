"""e-GRAS status vocabulary → normalised ``ProviderStatus`` (spec 0022 #6.3).

Unknown vocabulary maps to ``PENDING``, never ``FAILED``: e-GRAS explicitly asks
departments to re-check any status they do not recognise, and failing early
risks money taken with no credit. The amount comparison against the Dristi
payment happens in ``apps.payments`` (0017 #9.5) — the provider only reports.
"""

import logging
from collections.abc import Mapping
from datetime import datetime, time
from decimal import Decimal, InvalidOperation

from apps.payments.providers.base import (
    ProviderOutcome,
    ProviderStatus,
    ProviderTransientError,
)

from . import constants

logger = logging.getLogger(constants.LOGGER_NAME)

_BANKDATE_FORMAT = "%d/%m/%Y"


def map_status_text(text: str) -> ProviderOutcome:
    """Best-effort outcome for a status string (callback hint or verification)."""

    normalised = (text or "").strip().lower()
    if normalised in constants.STATUS_SUCCESS:
        return ProviderOutcome.SUCCESS
    if normalised == constants.STATUS_FAILURE:
        return ProviderOutcome.FAILED
    if normalised == constants.STATUS_NOT_FOUND:
        return ProviderOutcome.NOT_FOUND
    if normalised == constants.STATUS_PENDING:
        return ProviderOutcome.PENDING
    return ProviderOutcome.PENDING


def _decimal(value: str) -> Decimal | None:
    """Parse an amount string to ``Decimal``; ``None`` when not a number."""

    try:
        return Decimal((value or "").strip())
    except InvalidOperation:
        return None


def _paid_at(bankdate: str) -> datetime | None:
    """``dd/mm/yyyy`` at IST midnight, or ``None`` when unparsable."""

    try:
        naive = datetime.strptime((bankdate or "").strip(), _BANKDATE_FORMAT)
    except ValueError:
        return None
    return datetime.combine(naive.date(), time.min, tzinfo=constants.IST)


def map_grn_details(details: Mapping[str, str], *, provider_payment_id: str) -> ProviderStatus:
    """Map a parsed ``<GrnDetails>`` document to a ``ProviderStatus`` (#6.3)."""

    status_raw = (details.get(constants.STATUS_ELEMENT, "") or "").strip()
    status = status_raw.lower()
    grn = (details.get(constants.GRN_ELEMENT, "") or "").strip()
    cin = (details.get(constants.CIN_ELEMENT, "") or "").strip()
    amount_raw = (details.get(constants.AMOUNT_ELEMENT, "") or "").strip()
    bankdate = (details.get(constants.BANKDATE_ELEMENT, "") or "").strip()
    amount = _decimal(amount_raw)

    # The e-GRAS "try later" response: nothing populated. Transient, so the
    # poller tries again rather than resolving the payment on an empty answer.
    if not any((grn, cin, amount_raw, bankdate)) and status in ("", constants.STATUS_PENDING):
        raise ProviderTransientError(
            constants.EGRAS_VERIFY_EMPTY,
            "e-GRAS returned an empty GRN status response.",
        )

    metadata = {"cin": cin, "bank_date": bankdate, "egras_status": status_raw}

    def build(outcome, *, failure_code="", failure_message="", with_receipt=False):
        return ProviderStatus(
            provider_payment_id=provider_payment_id,
            outcome=outcome,
            amount=amount if with_receipt else None,
            provider_reference=grn if with_receipt else "",
            paid_at=_paid_at(bankdate) if with_receipt else None,
            failure_code=failure_code,
            failure_message=failure_message,
            metadata=metadata,
        )

    if status in constants.STATUS_SUCCESS:
        if grn and cin and amount is not None and amount == amount.to_integral_value():
            return build(ProviderOutcome.SUCCESS, with_receipt=True)
        return build(ProviderOutcome.PENDING, failure_code=constants.EGRAS_SUCCESS_INCOMPLETE)

    if status == constants.STATUS_FAILURE:
        return build(
            ProviderOutcome.FAILED,
            failure_code=constants.EGRAS_PAYMENT_FAILED,
            failure_message=constants.FAILURE_MESSAGE,
        )

    if status == constants.STATUS_PENDING:
        return build(ProviderOutcome.PENDING)

    if status == constants.STATUS_NOT_FOUND:
        return build(ProviderOutcome.NOT_FOUND)

    logger.warning(
        "event=%s provider_payment_id=%s egras_status=%r outcome=PENDING",
        constants.EGRAS_UNKNOWN_STATUS,
        provider_payment_id,
        status_raw,
    )
    return build(ProviderOutcome.PENDING, failure_code=constants.EGRAS_UNKNOWN_STATUS)
