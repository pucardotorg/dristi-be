"""Turning an initiation request into instructions for the payer (spec 0032 #5).

No network call and no state: the reference is derived from the request, so a
replay of the same request yields the same instructions.
"""

import logging
from decimal import Decimal

from apps.payments.providers.base import (
    ActionDetail,
    ActionKind,
    InitiationRequest,
    ProviderAction,
    ProviderInitiation,
    ProviderPermanentError,
)

from . import constants, methods, reference, validity
from .config import Counter, OfflineConfig

logger = logging.getLogger(__name__)


def build(request: InitiationRequest, config: OfflineConfig) -> ProviderInitiation:
    """Validate ``request`` and return its reference and instructions (#5.1)."""

    # The kill switch, the cap and the charge filter gate NEW requests only; a
    # replay of a request already issued rebuilds its instructions (#12.3).
    if not config.enabled and not request.replay:
        raise ProviderPermanentError(
            constants.OFFLINE_DISABLED, "Offline payment is not available right now."
        )
    if request.currency != constants.CURRENCY:
        raise ProviderPermanentError(
            constants.OFFLINE_UNSUPPORTED_CURRENCY, "Offline payments are collected in INR only."
        )
    amount = Decimal(request.amount)
    if amount <= 0 or amount != sum((Decimal(line.amount) for line in request.lines), Decimal(0)):
        raise ProviderPermanentError(
            constants.OFFLINE_AMOUNT_INCONSISTENT, "The amount does not match its charges."
        )
    cap = config.max_amount
    if cap is not None and amount > cap and not request.replay:
        raise ProviderPermanentError(
            constants.OFFLINE_AMOUNT_TOO_LARGE, f"Amounts above {cap:.2f} cannot be paid offline."
        )
    if config.allowed_charge_types and not request.replay:
        allowed = set(config.allowed_charge_types)
        if any(line.charge_type not in allowed for line in request.lines):
            raise ProviderPermanentError(
                constants.OFFLINE_CHARGE_NOT_ALLOWED,
                "One of these charges cannot be paid offline.",
            )
    counter = _counter(request, config)

    ref = reference.build(request.reference, request.initiated_at, config.reference_prefix)
    deadline = validity.valid_until(validity.ist_date(request.initiated_at), config)
    logger.info(
        "event=%s provider_payment_id=%s amount=%s counter=%s valid_until=%s",
        constants.EVENT_REQUEST_ISSUED,
        ref,
        f"{amount:.2f}",
        counter.code if counter else "",
        deadline.isoformat(),
    )
    return ProviderInitiation(
        provider_payment_id=ref,
        action=ProviderAction(
            kind=ActionKind.SHOW_INSTRUCTIONS,
            method="",
            details=_details(request, config, ref, amount, deadline, counter),
        ),
        # Nothing personal (spec 0017 #9.2 rule 8).
        metadata={
            "valid_until": deadline.isoformat(),
            "counter": counter.code if counter else "",
        },
    )


def _counter(request: InitiationRequest, config: OfflineConfig) -> Counter | None:
    """The counter the payer chose, the default one, or none (#5.3)."""

    chosen = str(request.options.get(constants.COUNTER_OPTION) or "").strip()
    if chosen:
        counter = config.counter(chosen)
        if counter is None:
            raise ProviderPermanentError(
                constants.OFFLINE_INVALID_COUNTER,
                "This counter does not accept payments.",
                field=constants.COUNTER_OPTION,
            )
        return counter
    if not config.counters:
        return None
    if config.default_counter:
        return config.counter(config.default_counter)
    if len(config.counters) == 1:
        return config.counters[0]
    raise ProviderPermanentError(
        constants.OFFLINE_COUNTER_REQUIRED,
        "Choose the counter where you will pay.",
        field=constants.COUNTER_OPTION,
    )


def format_amount(amount: Decimal) -> str:
    """``₹ 707.50``: two decimals, no rounding (the amount has at most two)."""

    return f"₹ {amount:.2f}"


def _details(request, config, ref, amount, deadline, counter) -> tuple[ActionDetail, ...]:
    accepted = methods.enabled(config)
    accepted_codes = {item.code for item in accepted}
    rows = [
        ("reference", "Payment reference", ref),
        ("amount", "Amount to pay", format_amount(amount)),
        ("valid_until", "Pay before", validity.format_ist(deadline)),
        ("counter", "Where to pay", counter.label if counter else ""),
        ("counter_address", "Address", counter.address if counter else ""),
        ("counter_hours", "Counter hours", counter.hours if counter else ""),
        ("methods", "Accepted", ", ".join(item.label for item in accepted)),
        (
            "payable_to",
            "Demand draft in favour of",
            config.payable_to if constants.DEMAND_DRAFT in accepted_codes else "",
        ),
        ("payments", "Payment numbers", ", ".join(request.payment_numbers)),
        ("instructions", "Instructions", config.instructions),
    ]
    # A detail with an empty value is omitted (#5.4).
    return tuple(ActionDetail(key, label, value) for key, label, value in rows if value)
