"""e-GRAS status vocabulary → normalised ``ProviderStatus`` (spec 0022 #6.3).

Unknown vocabulary maps to ``PENDING``, never ``FAILED``: e-GRAS explicitly asks
departments to re-check any status they do not recognise, and failing early
risks money taken with no credit. The amount comparison against the Dristi
payment happens in ``apps.payments`` (0017 #9.5) — the provider only reports.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace
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

# Selection order when an ArrayOfGrnDetails holds several records for one
# application number: a collected payment (SUCCESS) always wins, and a payment
# that may still complete (PENDING, then NOT_FOUND) is never overridden by a
# FAILED record — so money that is in, or on its way, is never marked failed.
_OUTCOME_PRIORITY = {
    ProviderOutcome.SUCCESS: 3,
    ProviderOutcome.PENDING: 2,
    ProviderOutcome.NOT_FOUND: 1,
    ProviderOutcome.FAILED: 0,
}


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


def _status_for_record(
    record: Mapping[str, str], provider_payment_id: str
) -> ProviderStatus | None:
    """Map one ``<GrnDetails>`` record to a ``ProviderStatus``, or ``None``.

    ``None`` means an empty "try later" record (nothing populated, status blank
    or ``Pending``): it carries no outcome of its own and is skipped so a sibling
    record with a real outcome is used instead.
    """

    status_raw = (record.get(constants.STATUS_ELEMENT, "") or "").strip()
    status = status_raw.lower()
    grn = (record.get(constants.GRN_ELEMENT, "") or "").strip()
    cin = (record.get(constants.CIN_ELEMENT, "") or "").strip()
    amount_raw = (record.get(constants.AMOUNT_ELEMENT, "") or "").strip()
    bankdate = (record.get(constants.BANKDATE_ELEMENT, "") or "").strip()
    amount = _decimal(amount_raw)

    if not any((grn, cin, amount_raw, bankdate)) and status in ("", constants.STATUS_PENDING):
        return None

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


def map_grn_records(
    records: Sequence[Mapping[str, str]], *, provider_payment_id: str
) -> ProviderStatus:
    """Map an ``ArrayOfGrnDetails`` to a single ``ProviderStatus`` (spec 0022 #6.3).

    Each record is classified on its own (fields are never mixed across records).
    A ``SUCCESS`` record always wins; more than one success for the same
    application number is a double payment, credited once and flagged for
    reconciliation. Otherwise the highest-priority outcome is chosen, so a
    FAILED record never overrides a sibling that is in or still pending. When no
    record carries an outcome, the lookup is transient ("try later").
    """

    statuses = [
        status
        for record in records
        if (status := _status_for_record(record, provider_payment_id)) is not None
    ]
    if not statuses:
        raise ProviderTransientError(
            constants.EGRAS_VERIFY_EMPTY,
            "e-GRAS returned an empty GRN status response.",
        )

    successes = [status for status in statuses if status.outcome == ProviderOutcome.SUCCESS]
    if len(successes) > 1:
        grns = [status.provider_reference for status in successes]
        logger.warning(
            "event=%s provider_payment_id=%s success_grns=%s",
            constants.EVENT_MULTIPLE_SUCCESS,
            provider_payment_id,
            grns,
        )
        chosen = successes[0]
        return replace(
            chosen,
            metadata={**chosen.metadata, "needs_reconciliation": True, "success_grns": grns},
        )

    return max(statuses, key=lambda status: _OUTCOME_PRIORITY[status.outcome])


def map_grn_details(details: Mapping[str, str], *, provider_payment_id: str) -> ProviderStatus:
    """Map a single ``<GrnDetails>`` record (convenience over :func:`map_grn_records`)."""

    return map_grn_records([details], provider_payment_id=provider_payment_id)
