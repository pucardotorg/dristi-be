"""Build the e-GRAS e-Challan form fields from an initiation request (spec 0022 #4).

``build_request`` makes no network call: it only assembles form fields, so it
can fail only permanently (configuration, mapping, payer, amount) and is
deterministic — the same request, including its ``initiated_at``, always yields
the same form, which keeps idempotent replay stable even across 31 March.
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from apps.payments.providers.base import InitiationRequest, ProviderPermanentError

from . import constants, sanitise
from .schemes import build_schemes

logger = logging.getLogger(constants.LOGGER_NAME)

SUPPORTED_CURRENCY = "INR"
_NON_DIGIT = re.compile(r"\D")


@dataclass(frozen=True)
class EGRASRequest:
    """The assembled e-GRAS request: the correlation id, form and metadata."""

    provider_payment_id: str
    form_fields: dict[str, str]
    metadata: dict


def financial_year(initiated_at) -> str:
    """Indian financial year (1 Apr – 31 Mar) of ``initiated_at`` in IST (#4.5).

    Written as the last two digits of each year, e.g. FY 2026-27 -> ``"2627"``.
    """

    local = initiated_at.astimezone(constants.IST)
    start = local.year if local.month >= 4 else local.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def application_number(reference: UUID, prefix: str) -> str:
    """Deterministic ``Applicationnumber`` from the payment/batch reference (#4.4)."""

    body = reference.hex.upper()[: constants.MAX_APPLICATION_NUMBER - len(prefix)]
    return f"{prefix}{body}"


def build_remarks(demand_numbers: tuple[str, ...], template: str) -> str:
    """Render the remarks, cutting a large batch to ``... and N more`` (#4.7)."""

    full = sanitise.clean(
        template.format(demand_numbers=" ".join(demand_numbers)),
        sanitise.REMARKS_ALLOWED,
        len(template) + sum(len(number) for number in demand_numbers) + 1,
    )
    if len(full) <= sanitise.MAX_REMARKS:
        return full

    total = len(demand_numbers)
    for keep in range(total - 1, 0, -1):
        candidate = sanitise.clean(
            template.format(demand_numbers=" ".join(demand_numbers[:keep]))
            + f" and {total - keep} more",
            sanitise.REMARKS_ALLOWED,
            sanitise.MAX_REMARKS + 1,
        )
        if len(candidate) <= sanitise.MAX_REMARKS:
            return candidate
    return full[: sanitise.MAX_REMARKS]


def select_bank(options, config) -> str:
    """Resolve the bank code from the client's choice or the default (#4.6)."""

    requested = (options.get(constants.FIELD_BANK, "") or "").strip()
    bank = requested or config.default_bank
    codes = {option.code for option in config.bank_options}
    if not bank:
        raise ProviderPermanentError(
            constants.EGRAS_BANK_REQUIRED,
            "A bank must be chosen and no EGRAS_DEFAULT_BANK is configured.",
            field=constants.FIELD_BANK,
        )
    if bank not in codes:
        raise ProviderPermanentError(
            constants.EGRAS_INVALID_BANK,
            f"{bank!r} is not a configured e-GRAS bank code.",
            field=constants.FIELD_BANK,
        )
    return bank


def _mask_payer(payer) -> str:
    """Name initial and the last four phone digits only (spec 0022 #11)."""

    name = (payer.name or "").strip()
    phone = _NON_DIGIT.sub("", payer.phone or "")
    masked_name = f"{name[0]}***" if name else "-"
    masked_phone = f"****{phone[-4:]}" if len(phone) >= 4 else "-"
    return f"name={masked_name} phone={masked_phone}"


def build_request(request: InitiationRequest, config) -> EGRASRequest:
    """Assemble the e-GRAS form fields for one collection (spec 0022 #4)."""

    if request.currency != SUPPORTED_CURRENCY:
        raise ProviderPermanentError(
            constants.EGRAS_UNSUPPORTED_CURRENCY,
            f"e-GRAS collects only {SUPPORTED_CURRENCY}, not {request.currency!r}.",
        )

    schemes = build_schemes(
        request.lines, scheme_map=config.scheme_map, max_schemes=config.max_schemes
    )
    total = sum(scheme.amount for scheme in schemes)
    if request.amount <= 0 or Decimal(total) != request.amount:
        raise ProviderPermanentError(
            constants.EGRAS_AMOUNT_INCONSISTENT,
            f"Request amount {request.amount} does not equal the scheme total {total}.",
        )

    payer = sanitise.sanitise_payer(request.payer, config)
    bank = select_bank(request.options, config)
    provider_payment_id = application_number(request.reference, config.application_prefix)

    form_fields = {
        constants.FIELD_DTO: config.dto,
        constants.FIELD_STO: config.sto,
        constants.FIELD_DDO: config.ddo,
        constants.FIELD_DEPT_CODE: config.dept_code,
        constants.FIELD_OFFICE_NAME: config.effective_office_name,
        constants.FIELD_USER_ID: config.user_id,
        constants.FIELD_CHALLAN_YEAR: financial_year(request.initiated_at),
        constants.FIELD_APPLICATION_NUMBER: provider_payment_id,
        constants.FIELD_FULLNAME: payer.fullname,
        constants.FIELD_CITYNAME: payer.cityname,
        constants.FIELD_ADDRESS: payer.address,
        constants.FIELD_PINCODE: payer.pincode,
        constants.FIELD_SECURITY_EMAIL: payer.email,
        constants.FIELD_SECURITY_PHONE: payer.phone,
        constants.FIELD_BANK: bank,
        constants.FIELD_PTYPE: constants.PTYPE_NET_BANKING,
        constants.FIELD_REMARKS: build_remarks(request.demand_numbers, config.remarks_template),
        constants.FIELD_TOTAL_AMOUNT: str(total),
        constants.FIELD_SCHEME_COUNT: str(len(schemes)),
        constants.FIELD_UURL: config.return_url,
    }
    for index, scheme in enumerate(schemes, start=constants.FIRST_SCHEME_INDEX):
        form_fields[constants.scheme_name_field(index)] = scheme.code
        form_fields[constants.fee_amount_field(index)] = str(scheme.amount)

    metadata = {
        "schemes": [{"code": scheme.code, "amount": scheme.amount} for scheme in schemes],
        "bank": bank,
        "total": total,
    }

    logger.info(
        "event=%s provider_payment_id=%s scheme_count=%d total=%d bank=%s %s",
        constants.EVENT_REQUEST_BUILT,
        provider_payment_id,
        len(schemes),
        total,
        bank,
        _mask_payer(request.payer),
    )
    return EGRASRequest(
        provider_payment_id=provider_payment_id, form_fields=form_fields, metadata=metadata
    )
