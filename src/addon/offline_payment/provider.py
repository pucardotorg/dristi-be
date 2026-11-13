"""The offline payment provider (spec 0032 #11).

This is the only class ``apps.payments`` knows about, and it knows it by its
dotted path in ``PAYMENT_PROVIDERS``. It holds no state, touches no model and
makes no network call: it receives and returns the frozen dataclasses of the
0017 contract. Money is credited only through an attestation recorded by an
authorised person (``attest``); ``fetch_status`` never reports ``SUCCESS`` and
there is no callback.
"""

import logging
from collections.abc import Mapping

from django.utils import timezone

from apps.payments.providers.base import (
    Attestation,
    AttestationMethod,
    ConfirmationMode,
    InitiationRequest,
    PaymentOption,
    PaymentProvider,
    ProviderCallback,
    ProviderCallbackMalformed,
    ProviderInitiation,
    ProviderOutcome,
    ProviderPermanentError,
    ProviderStatus,
)

from . import attestation as attestation_rules
from . import constants, instructions, methods, reference, validity
from .config import resolve_config

logger = logging.getLogger(__name__)


class OfflinePaymentProvider(PaymentProvider):
    """Money handed over in person and recorded by court staff."""

    name = constants.PROVIDER_NAME
    confirmation = ConfirmationMode.ATTESTED

    @property
    def label(self) -> str:
        """``OFFLINE_PAYMENT_LABEL``, shown in the provider list."""

        return resolve_config().label

    @property
    def pending_horizon(self):
        """Validity + grace + 1 day: the poller fails a request before flagging it (#6.3)."""

        return resolve_config().pending_horizon

    @property
    def not_found_grace(self):
        """Same as ``pending_horizon``: ``NOT_FOUND`` only means "not ours" (#6.3)."""

        return resolve_config().pending_horizon

    def list_options(self) -> list[PaymentOption]:
        """The configured counters, in order (#5.3)."""

        return [
            PaymentOption(code=counter.code, label=counter.label, group=constants.COUNTER_GROUP)
            for counter in resolve_config().counters
        ]

    def initiate(self, request: InitiationRequest) -> ProviderInitiation:
        """Derive the reference and the instructions. No I/O; deterministic (#5)."""

        return instructions.build(request, resolve_config())

    def fetch_status(self, *, provider_payment_id: str) -> ProviderStatus:
        """``PENDING`` until the request expires, then ``FAILED``; never ``SUCCESS`` (#6.2)."""

        config = resolve_config()
        try:
            parsed = reference.parse(provider_payment_id, config.reference_prefix)
        except reference.MalformedReference:
            return _status(provider_payment_id, ProviderOutcome.NOT_FOUND)
        if not validity.is_expired(parsed.issued_on, config, timezone.now()):
            return _status(provider_payment_id, ProviderOutcome.PENDING)
        logger.info(
            "event=%s provider_payment_id=%s",
            constants.EVENT_REQUEST_EXPIRED,
            provider_payment_id,
        )
        return _status(
            provider_payment_id,
            ProviderOutcome.FAILED,
            failure_code=constants.OFFLINE_REQUEST_EXPIRED,
            failure_message=constants.EXPIRED_MESSAGE,
        )

    def parse_callback(self, payload: Mapping[str, str]) -> ProviderCallback:
        """There is no callback: nothing remote may report an offline payment (#7)."""

        raise ProviderCallbackMalformed(
            constants.OFFLINE_NO_CALLBACK, "Offline payments have no callback."
        )

    def attestation_methods(self) -> list[AttestationMethod]:
        """The enabled collection methods and their fields (#8.1)."""

        return methods.enabled(resolve_config())

    def attest(self, attestation: Attestation) -> ProviderStatus:
        """Validate what staff recorded; pure (#8.2)."""

        return attestation_rules.attest(attestation, resolve_config())

    def normalise_reference(self, value: str) -> str:
        """The canonical reference; refuses a value that fails its check symbol (#5.2)."""

        try:
            return reference.normalise(value, resolve_config().reference_prefix)
        except reference.MalformedReference as exc:
            raise ProviderPermanentError(
                constants.OFFLINE_REFERENCE_MALFORMED, "This is not a valid payment reference."
            ) from exc


def _status(provider_payment_id, outcome, *, failure_code="", failure_message=""):
    return ProviderStatus(
        provider_payment_id=provider_payment_id,
        outcome=outcome,
        amount=None,
        provider_reference="",
        paid_at=None,
        failure_code=failure_code,
        failure_message=failure_message,
        metadata={},
    )
