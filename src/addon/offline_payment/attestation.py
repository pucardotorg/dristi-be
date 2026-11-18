"""Validating what staff recorded and mapping it to a status (spec 0032 #8.2).

``attest`` is pure: it validates and maps, stores nothing and calls no network.
Whether the request is still open, who may record it and whether the receipt
number was used before are decided by ``apps.payments`` under a lock. The rules
run in the order of #8.2 and the first failing one is reported.
"""

import logging
import re
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

from apps.payments.providers.base import (
    Attestation,
    AttestationField,
    ProviderOutcome,
    ProviderPermanentError,
    ProviderStatus,
)

from . import constants, methods, reference, validity
from .config import OfflineConfig

logger = logging.getLogger(__name__)

ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
DIGITS = re.compile(r"[0-9]+")
# Printable text without control characters; instrument data is shown on receipts.
PRINTABLE = re.compile(r"[^\x00-\x1f\x7f]*")


def reject(code: str, message: str, field: str | None = None):
    """Log and raise the refusal of one rule."""

    logger.info(
        "event=%s failure_code=%s field=%s",
        constants.EVENT_ATTESTATION_REJECTED,
        code,
        field or "",
    )
    raise ProviderPermanentError(code, message, field=field)


def attest(attestation: Attestation, config: OfflineConfig, *, now: datetime | None = None):
    """Validate ``attestation``; return the ``SUCCESS`` status to apply."""

    now = now or timezone.now()

    # 1. One of our references.
    try:
        parsed = reference.parse(attestation.provider_payment_id, config.reference_prefix)
    except reference.MalformedReference:
        reject(constants.OFFLINE_REFERENCE_MALFORMED, "This is not an offline payment reference.")

    # 2. Currency.
    if attestation.currency != constants.CURRENCY:
        reject(
            constants.OFFLINE_UNSUPPORTED_CURRENCY,
            "Offline payments are collected in INR only.",
        )

    # 3. Method enabled.
    method_code = (attestation.method or "").strip().upper()
    if method_code not in methods.enabled_codes(config):
        reject(
            constants.OFFLINE_METHOD_NOT_ALLOWED,
            "This collection method is not accepted.",
            "method",
        )

    # 4. Exact amount, at most two decimals.
    amount = _decimal(attestation.amount)
    if (
        amount is None
        or amount.as_tuple().exponent < -2
        or amount != Decimal(attestation.expected_amount)
    ):
        reject(
            constants.OFFLINE_AMOUNT_MISMATCH,
            f"The amount must be exactly {Decimal(attestation.expected_amount):.2f}.",
            "amount",
        )

    # 5. Cash cap.
    cash_cap = config.cash_max_amount
    if method_code == constants.CASH and cash_cap is not None and amount > cash_cap:
        reject(
            constants.OFFLINE_CASH_LIMIT_EXCEEDED,
            f"Cash above {cash_cap:.2f} is not accepted.",
            "amount",
        )

    # 6. Receipt number.
    receipt = str(attestation.receipt_number or "").strip().upper()
    pattern = config.receipt_re
    if not receipt or pattern is None or not pattern.fullmatch(receipt):
        reject(
            constants.OFFLINE_RECEIPT_INVALID,
            "The receipt number is not in the expected format.",
            "receipt_number",
        )

    # 7-10. When the money was handed over.
    collected_at = attestation.collected_at
    if not isinstance(collected_at, datetime) or timezone.is_naive(collected_at):
        reject(
            constants.OFFLINE_COLLECTED_AT_INVALID,
            "The collection time must include a time zone.",
            "collected_at",
        )
    if collected_at < attestation.initiated_at:
        reject(
            constants.OFFLINE_COLLECTED_BEFORE_REQUEST,
            "The money cannot have been collected before the payment request was made.",
            "collected_at",
        )
    if collected_at > now + constants.CLOCK_SKEW:
        reject(
            constants.OFFLINE_COLLECTED_IN_FUTURE,
            "The collection time is in the future.",
            "collected_at",
        )
    deadline = validity.valid_until(parsed.issued_on, config)
    if collected_at > deadline:
        reject(
            constants.OFFLINE_COLLECTED_AFTER_EXPIRY,
            f"The request was valid until {validity.format_ist(deadline)}.",
            "collected_at",
        )

    # 11. Recording deadline, unless apps.payments is recording late (#8.5).
    if not attestation.late and validity.is_expired(parsed.issued_on, config, now):
        reject(constants.OFFLINE_REQUEST_EXPIRED, constants.EXPIRED_MESSAGE)

    # 12-14. Instrument details.
    details = _validate_details(method_code, attestation.details or {}, collected_at, config)

    # 15. Remarks.
    if len(attestation.remarks or "") > constants.REMARKS_MAX_LENGTH:
        reject(
            constants.OFFLINE_REMARKS_TOO_LONG,
            f"Remarks may be at most {constants.REMARKS_MAX_LENGTH} characters.",
            "remarks",
        )

    return ProviderStatus(
        provider_payment_id=attestation.provider_payment_id,
        outcome=ProviderOutcome.SUCCESS,
        amount=amount,
        provider_reference=receipt,
        paid_at=collected_at,
        failure_code="",
        failure_message="",
        metadata={"method": method_code, "collected_at": collected_at.isoformat(), **details},
    )


def _decimal(value) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _validate_details(method_code, raw, collected_at, config) -> dict[str, str]:
    """Rules 12-14: required and unknown keys, kinds and lengths, DD dates."""

    fields = {field.key: field for field in methods.method(method_code).fields}
    values = {str(key): "" if value is None else str(value).strip() for key, value in raw.items()}

    # 12. Every required field present; no unknown keys.
    for key in values:
        if key not in fields:
            reject(
                constants.OFFLINE_DETAIL_UNKNOWN,
                "This detail does not apply to the collection method.",
                f"details.{key}",
            )
    for key, spec in fields.items():
        if spec.required and not values.get(key):
            reject(constants.OFFLINE_DETAIL_REQUIRED, "This detail is required.", f"details.{key}")

    # 13. Kind and length of each value given.
    cleaned = {}
    for key, spec in fields.items():
        value = values.get(key, "")
        if not value:
            continue
        if not _valid_value(method_code, spec, value):
            reject(constants.OFFLINE_DETAIL_INVALID, "This detail is not valid.", f"details.{key}")
        cleaned[key] = value

    # 14. Demand draft date.
    if method_code == constants.DEMAND_DRAFT:
        drawn_on = date.fromisoformat(cleaned[constants.INSTRUMENT_DATE])
        collected_on = validity.ist_date(collected_at)
        field = f"details.{constants.INSTRUMENT_DATE}"
        if drawn_on > collected_on:
            reject(
                constants.OFFLINE_DD_DATE_INVALID,
                "A demand draft cannot be dated after it was handed over.",
                field,
            )
        if collected_on - drawn_on > config.dd_max_age:
            reject(constants.OFFLINE_DD_STALE, "This demand draft is too old.", field)
    return cleaned


def _valid_value(method_code: str, spec: AttestationField, value: str) -> bool:
    rule = methods.rule(method_code, spec.key)
    if len(value) > spec.max_length or len(value) < rule.min_length:
        return False
    if not PRINTABLE.fullmatch(value):
        return False
    if rule.pattern is not None and not rule.pattern.fullmatch(value):
        return False
    if spec.kind == constants.KIND_DIGITS:
        return bool(DIGITS.fullmatch(value))
    if spec.kind == constants.KIND_DATE:
        if not ISO_DATE.fullmatch(value):
            return False
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
    return True
