"""The e-GRAS payment provider (spec 0022 #7).

This is the only class ``apps.payments`` knows about, and it knows it by its
dotted path in ``PAYMENT_PROVIDERS``. Everything e-GRAS specific — the e-Challan
form, the untrusted callback, the SOAP GRN lookup and the status vocabulary —
stops here. The provider holds no state and touches no model: it receives and
returns the frozen dataclasses of the 0017 contract.
"""

from collections.abc import Mapping

from apps.payments.providers.base import (
    ActionKind,
    InitiationRequest,
    PaymentOption,
    PaymentProvider,
    ProviderAction,
    ProviderCallback,
    ProviderInitiation,
    ProviderPermanentError,
    ProviderStatus,
)

from . import constants
from .callback_parser import parse
from .config import resolve_config
from .request_builder import build_request
from .status_mapper import map_grn_records
from .verification_client import fetch_grn_records


class EGRASPaymentProvider(PaymentProvider):
    """Collect payments into government heads of account through e-GRAS."""

    name = constants.PROVIDER_NAME

    @property
    def pending_horizon(self):
        """e-GRAS declares failure on the 8th day; default nine days (#6.4)."""

        return resolve_config().pending_horizon

    @property
    def not_found_grace(self):
        """How long a missing GRN may stay ``NOT_FOUND`` before it is final (#6.4)."""

        return resolve_config().not_found_grace

    def list_options(self) -> list[PaymentOption]:
        """The configured bank/UPI choices, as opaque payment options (#4.6)."""

        return [
            PaymentOption(code=bank.code, label=bank.label, group=bank.group)
            for bank in resolve_config().bank_options
        ]

    def initiate(self, request: InitiationRequest) -> ProviderInitiation:
        """Build the e-Challan redirect form. No network call: local and deterministic."""

        config = resolve_config()
        if not config.enabled:
            raise ProviderPermanentError(
                constants.EGRAS_DISABLED,
                "e-GRAS is disabled; new payments cannot be initiated.",
            )

        built = build_request(request, config)
        return ProviderInitiation(
            provider_payment_id=built.provider_payment_id,
            action=ProviderAction(
                kind=ActionKind.REDIRECT_FORM,
                url=config.payment_url,
                method="POST",
                form_fields=built.form_fields,
            ),
            metadata=built.metadata,
        )

    def fetch_status(self, *, provider_payment_id: str) -> ProviderStatus:
        """Verify the payment by its identity through the SOAP GRN lookup (#6)."""

        config = resolve_config()
        records = fetch_grn_records(config, provider_payment_id=provider_payment_id)
        return map_grn_records(records, provider_payment_id=provider_payment_id)

    def parse_callback(self, payload: Mapping[str, str]) -> ProviderCallback:
        """Parse the return-URL form; ``trusted`` is always ``False`` (#5)."""

        return parse(payload, resolve_config())
