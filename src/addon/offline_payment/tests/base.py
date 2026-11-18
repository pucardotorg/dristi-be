"""Builders shared by the offline addon tests."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest import mock

from addon.offline_payment.constants import IST
from apps.payments.providers.base import Attestation, ChargeLine, InitiationRequest, Payer

# 11 Nov 2026, 09:00 IST: the worked example of spec 0032 #6.1.
ISSUED_AT = datetime(2026, 11, 11, 9, 0, tzinfo=IST)
REFERENCE_UUID = uuid.UUID("2b7d4c1e-9a3f-4e21-8b6d-5f0a1c2e3d4f")
COUNTERS = [
    {
        "code": "EKM-CJM",
        "label": "CJM Court, Ernakulam — Fee counter",
        "address": "Ground floor, District Court Complex, Ernakulam 682011",
        "hours": "Mon–Fri 10:30–16:00",
    },
    {"code": "EKM-MC", "label": "Munsiff Court, Ernakulam", "address": "", "hours": ""},
]


def ist(*args) -> datetime:
    """An aware IST datetime."""

    return datetime(*args, tzinfo=IST)


def line(amount="12.50", charge_type="COURT_FEE", payment_id=None):
    return ChargeLine(
        payment_id=payment_id or uuid.uuid4(),
        demand_number="DMD-2026-000123",
        demand_item_id=uuid.uuid4(),
        charge_type=charge_type,
        account_head="",
        description="Court fee",
        amount=Decimal(amount),
    )


def initiation_request(
    *,
    amounts=("700.00", "7.50"),
    charge_types=None,
    amount=None,
    currency="INR",
    options=None,
    reference=REFERENCE_UUID,
    initiated_at=ISSUED_AT,
    payment_numbers=("PAY-2026-000456",),
):
    charge_types = charge_types or ["COURT_FEE"] * len(amounts)
    lines = tuple(line(a, c) for a, c in zip(amounts, charge_types, strict=True))
    return InitiationRequest(
        reference=reference,
        payment_numbers=tuple(payment_numbers),
        demand_numbers=("DMD-2026-000123",),
        lines=lines,
        amount=Decimal(amount) if amount is not None else sum(entry.amount for entry in lines),
        currency=currency,
        payer=Payer(name="Anjali Menon", email="anjali@example.com", phone="+919800003210"),
        initiated_at=initiated_at,
        options=dict(options or {}),
    )


def attestation(provider_payment_id, **overrides) -> Attestation:
    values = {
        "provider_payment_id": provider_payment_id,
        "expected_amount": Decimal("707.50"),
        "currency": "INR",
        "initiated_at": ISSUED_AT,
        "amount": Decimal("707.50"),
        "method": "CASH",
        "receipt_number": "CJM/EKM/2026/004512",
        "collected_at": ISSUED_AT + timedelta(days=1),
        "details": {},
        "remarks": "",
        "late": False,
    }
    values.update(overrides)
    return Attestation(**values)


def frozen_now(moment: datetime):
    """Patch ``django.utils.timezone.now`` (what every module calls) to ``moment``."""

    return mock.patch("django.utils.timezone.now", return_value=moment)
