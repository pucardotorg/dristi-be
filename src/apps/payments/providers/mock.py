"""A provider with no gateway behind it — the local/test default (spec 0017 #9.8).

The outcome is chosen by the payer through ``provider_options["outcome"]``
(``SUCCESS``, ``FAILED``, ``PENDING``, ``NOT_FOUND``) and encoded, with the
amount, into the provider payment id. That keeps the mock stateless and
deterministic: ``initiate`` is replayable, and ``fetch_status`` answers the
same thing in any process. A system check refuses it in production.
"""

from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.urls import reverse
from django.utils import timezone

from .. import conf
from .base import (
    ActionKind,
    InitiationRequest,
    PaymentOption,
    PaymentProvider,
    ProviderAction,
    ProviderCallback,
    ProviderCallbackMalformed,
    ProviderInitiation,
    ProviderOutcome,
    ProviderPermanentError,
    ProviderStatus,
)

OUTCOME_OPTION = "outcome"
ID_PREFIX = "MOCK"


class MockPaymentProvider(PaymentProvider):
    """Posts the browser straight back to the callback with a chosen outcome."""

    name = "mock"
    pending_horizon = timedelta(hours=1)
    not_found_grace = timedelta(minutes=15)

    def list_options(self) -> list[PaymentOption]:
        """One option per outcome, sent back as ``provider_options["outcome"]``."""

        return [
            PaymentOption(code=outcome.value, label=f"Mock: {outcome.value}", group="MOCK")
            for outcome in ProviderOutcome
        ]

    def initiate(self, request: InitiationRequest) -> ProviderInitiation:
        """Return a form that posts the encoded outcome to the callback endpoint."""

        raw = (request.options.get(OUTCOME_OPTION) or ProviderOutcome.SUCCESS.value).upper()
        try:
            outcome = ProviderOutcome(raw)
        except ValueError as exc:
            raise ProviderPermanentError(
                "MOCK_UNKNOWN_OUTCOME", f"Unknown mock outcome {raw!r}.", field=OUTCOME_OPTION
            ) from exc

        provider_payment_id = (
            f"{ID_PREFIX}-{request.reference.hex}-{outcome.value}-{request.amount}"
        )
        url = conf.mock_callback_base_url().rstrip("/") + reverse(
            "payments-provider-callback", kwargs={"provider": self.name}
        )
        return ProviderInitiation(
            provider_payment_id=provider_payment_id,
            action=ProviderAction(
                kind=ActionKind.REDIRECT_FORM,
                url=url,
                form_fields={"provider_payment_id": provider_payment_id, "outcome": outcome.value},
            ),
            metadata={"outcome": outcome.value},
        )

    def fetch_status(self, *, provider_payment_id: str) -> ProviderStatus:
        """Decode the outcome the payer chose at initiation."""

        outcome, amount = self._decode(provider_payment_id)
        return self._status(provider_payment_id, outcome, amount)

    def parse_callback(self, payload: Mapping[str, str]) -> ProviderCallback:
        """Trust the callback: the mock has nothing to verify."""

        provider_payment_id = (payload.get("provider_payment_id") or "").strip()
        outcome, amount = self._decode(provider_payment_id)
        return ProviderCallback(
            status=self._status(provider_payment_id, outcome, amount), trusted=True
        )

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _decode(provider_payment_id: str) -> tuple[ProviderOutcome, Decimal]:
        parts = provider_payment_id.split("-")
        if len(parts) != 4 or parts[0] != ID_PREFIX:
            raise ProviderCallbackMalformed("MOCK_MALFORMED", "Not a mock payment id.")
        try:
            return ProviderOutcome(parts[2]), Decimal(parts[3])
        except (ValueError, InvalidOperation) as exc:
            raise ProviderCallbackMalformed("MOCK_MALFORMED", "Not a mock payment id.") from exc

    @staticmethod
    def _status(provider_payment_id, outcome: ProviderOutcome, amount: Decimal) -> ProviderStatus:
        success = outcome == ProviderOutcome.SUCCESS
        failed = outcome == ProviderOutcome.FAILED
        return ProviderStatus(
            provider_payment_id=provider_payment_id,
            outcome=outcome,
            amount=amount if success else None,
            provider_reference=f"MOCKREF-{provider_payment_id.split('-')[1][:12].upper()}"
            if success
            else "",
            paid_at=timezone.now() if success else None,
            failure_code="MOCK_PAYMENT_FAILED" if failed else "",
            failure_message="The mock provider declined the payment." if failed else "",
            metadata={"outcome": outcome.value},
        )
