"""Shared fixtures for the e-GRAS payment gateway addon tests."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from django.test import override_settings

from addon.egras_payment_gateway import constants
from addon.egras_payment_gateway.config import BankOption, EGRASConfig
from apps.payments.providers.base import ChargeLine, InitiationRequest, Payer

# A complete, valid e-GRAS configuration. Individual tests override one value to
# exercise a single failure mode.
VALID_SETTINGS = {
    "PAYMENT_PROVIDERS": {
        "mock": "apps.payments.providers.mock.MockPaymentProvider",
        constants.PROVIDER_NAME: constants.PROVIDER_PATH,
    },
    "EGRAS_PAYMENT_URL": "https://egras.invalid/echallan",
    "EGRAS_VERIFY_URL": "https://egras.invalid/grnstatus",
    "EGRAS_RETURN_URL": "https://dristi.invalid/api/v1/payments/providers/egras/_callback",
    "EGRAS_DEPT_CODE": "DRI",
    "EGRAS_DTO": "01",
    "EGRAS_STO": "02",
    "EGRAS_DDO": "DDO1",
    "EGRAS_SCHEME_MAP": {"COURT_FEE": "0030-01-501-01-00"},
    "EGRAS_BANK_OPTIONS": [
        {"code": "SBI", "label": "State Bank of India", "group": "NET_BANKING"},
        {"code": "UPI", "label": "UPI", "group": "UPI"},
    ],
    "EGRAS_DEFAULT_BANK": "SBI",
}


class EGRASSettingsMixin:
    """Points the addon at a complete, valid e-GRAS configuration."""

    def configure(self, **overrides):
        """Apply a valid e-GRAS configuration, with ``overrides`` on top."""

        settings = {**VALID_SETTINGS, **overrides}
        patcher = override_settings(**settings)
        patcher.enable()
        self.addCleanup(patcher.disable)
        return settings


def make_config(**overrides) -> EGRASConfig:
    """A complete, valid :class:`EGRASConfig` for the pure-function tests."""

    base = {
        "payment_url": "https://egras.invalid/echallan",
        "verify_url": "https://egras.invalid/grnstatus",
        "return_url": "https://dristi.invalid/api/v1/payments/providers/egras/_callback",
        "dept_code": "DRI",
        "dto": "01",
        "sto": "02",
        "ddo": "DDO1",
        "scheme_map": {"COURT_FEE": "0030-01-501-01-00"},
        "bank_options": (
            BankOption("SBI", "State Bank of India", "NET_BANKING"),
            BankOption("UPI", "UPI", "UPI"),
        ),
        "default_bank": "SBI",
    }
    base.update(overrides)
    return EGRASConfig(**base)


def make_payer(**overrides) -> Payer:
    """A plausible payer; override one field to exercise sanitisation."""

    fields = {
        "name": "Ravi Kumar",
        "email": "ravi@example.com",
        "phone": "9876543210",
        "address": "12 MG Road",
        "city": "Kochi",
        "pincode": "682001",
    }
    fields.update(overrides)
    return Payer(**fields)


def make_line(
    amount, *, charge_type="COURT_FEE", account_head="", demand_number="DMD-1"
) -> ChargeLine:
    """One charge line with a decimal rupee amount."""

    return ChargeLine(
        payment_id=uuid4(),
        demand_number=demand_number,
        demand_item_id=uuid4(),
        charge_type=charge_type,
        account_head=account_head,
        description=charge_type,
        amount=Decimal(amount),
    )


def make_request(
    lines, *, reference=None, payer=None, options=None, initiated_at=None, **overrides
):
    """An :class:`InitiationRequest` whose amount defaults to the line sum."""

    lines = tuple(lines)
    amount = overrides.pop("amount", sum((line.amount for line in lines), Decimal(0)))
    demand_numbers = overrides.pop(
        "demand_numbers", tuple(dict.fromkeys(line.demand_number for line in lines))
    )
    return InitiationRequest(
        reference=reference or UUID("0f9d3a6c1b2e4f5a7b8c9d0e1f2a3b4c"),
        payment_numbers=overrides.pop("payment_numbers", ("PAY-1",)),
        demand_numbers=demand_numbers,
        lines=lines,
        amount=amount,
        currency=overrides.pop("currency", "INR"),
        payer=payer or make_payer(),
        initiated_at=initiated_at or datetime(2026, 10, 12, 9, 0, tzinfo=constants.IST),
        options=options if options is not None else {"bank": "SBI"},
    )
