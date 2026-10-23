"""A scriptable provider for contract tests (spec 0017 #18)."""

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal

from apps.payments.providers.base import (
    ActionKind,
    InitiationRequest,
    PaymentOption,
    PaymentProvider,
    ProviderAction,
    ProviderCallback,
    ProviderCallbackMalformed,
    ProviderInitiation,
    ProviderOutcome,
    ProviderStatus,
)


def status(provider_payment_id, outcome=ProviderOutcome.SUCCESS, amount=None, **extra):
    """A ``ProviderStatus`` with sensible defaults."""

    return ProviderStatus(
        provider_payment_id=provider_payment_id,
        outcome=ProviderOutcome(outcome),
        amount=None if amount is None else Decimal(str(amount)),
        provider_reference=extra.pop(
            "provider_reference", "RCPT-1" if outcome == "SUCCESS" else ""
        ),
        paid_at=None,
        failure_code=extra.pop("failure_code", "FAKE_FAILED" if outcome == "FAILED" else ""),
        failure_message=extra.pop("failure_message", ""),
        metadata=extra.pop("metadata", {}),
    )


class FakeProvider(PaymentProvider):
    """Records calls; answers from class-level scripts set by each test."""

    name = "fake"
    pending_horizon = timedelta(hours=2)
    not_found_grace = timedelta(minutes=30)

    initiate_error: Exception | None = None
    fetch_error: Exception | None = None
    statuses: dict = {}
    trusted = False
    id_suffix = ""
    initiate_calls: list = []
    fetch_calls: list = []

    @classmethod
    def reset(cls):
        cls.initiate_error = None
        cls.fetch_error = None
        cls.statuses = {}
        cls.trusted = False
        cls.id_suffix = ""
        cls.initiate_calls = []
        cls.fetch_calls = []

    def list_options(self):
        return [PaymentOption(code="BANK-01", label="Bank one", group="NET_BANKING")]

    def initiate(self, request: InitiationRequest) -> ProviderInitiation:
        type(self).initiate_calls.append(request)
        if self.initiate_error is not None:
            raise self.initiate_error
        provider_payment_id = f"FAKE{request.reference.hex[:16].upper()}{self.id_suffix}"
        return ProviderInitiation(
            provider_payment_id=provider_payment_id,
            action=ProviderAction(
                kind=ActionKind.REDIRECT_FORM,
                url="https://gateway.example/pay",
                form_fields={
                    "id": provider_payment_id,
                    "amount": str(request.amount),
                    "at": request.initiated_at.isoformat(),
                },
            ),
            metadata={"bank": request.options.get("bank", "")},
        )

    def fetch_status(self, *, provider_payment_id: str) -> ProviderStatus:
        type(self).fetch_calls.append(provider_payment_id)
        if self.fetch_error is not None:
            raise self.fetch_error
        return self.statuses.get(
            provider_payment_id, status(provider_payment_id, ProviderOutcome.NOT_FOUND)
        )

    def parse_callback(self, payload: Mapping[str, str]) -> ProviderCallback:
        provider_payment_id = payload.get("id", "")
        if not provider_payment_id:
            raise ProviderCallbackMalformed("FAKE_MALFORMED", "no id")
        claimed = status(
            provider_payment_id,
            payload.get("outcome", "SUCCESS"),
            amount=payload.get("amount") or None,
        )
        return ProviderCallback(status=claimed, trusted=self.trusted)
