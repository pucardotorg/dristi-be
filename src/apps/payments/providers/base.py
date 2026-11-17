"""The payment provider contract (spec 0017 #9.1).

The only surface an addon may import. Nothing here names a gateway. A provider
receives and returns frozen dataclasses: it never touches the ORM, never sees
a model and never calls ``PaymentService``, so it cannot write a balance.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar
from uuid import UUID


class ProviderOutcome(StrEnum):
    """A provider's verdict, normalised. Anything not understood is ``PENDING``."""

    SUCCESS = "SUCCESS"  # money collected and confirmed by the provider
    FAILED = "FAILED"  # provider says final failure
    PENDING = "PENDING"  # outcome not yet known
    NOT_FOUND = "NOT_FOUND"  # provider has no record of this transaction


class ConfirmationMode(StrEnum):
    """Who declares that the money was received (spec 0032 #4.1).

    ``ATTESTED`` providers are completed only by an authorised person through
    ``PaymentService.record_collection``; their ``fetch_status`` never credits.
    By convention an ``ATTESTED`` provider writes ``valid_until`` (an ISO-8601
    datetime) into the initiation metadata, so the collection desk can show
    until when the request may be paid without knowing the provider.
    """

    PROVIDER = "PROVIDER"  # the provider reports the outcome; fetch_status is authoritative
    ATTESTED = "ATTESTED"  # authorised staff record the collection through apps.payments


class ActionKind(StrEnum):
    """What the client does with ``provider_action``."""

    REDIRECT_FORM = "REDIRECT_FORM"  # browser posts form_fields to url
    SHOW_INSTRUCTIONS = "SHOW_INSTRUCTIONS"  # show details; nothing to submit
    NONE = "NONE"  # nothing for the client to do


@dataclass(frozen=True)
class Payer:
    """Who pays, as sent to the provider."""

    name: str
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    pincode: str = ""


@dataclass(frozen=True)
class ChargeLine:
    """One demand item being paid."""

    payment_id: UUID
    demand_number: str
    demand_item_id: UUID
    charge_type: str  # ChargeType value, as a plain string
    account_head: str  # DemandItem.account_head snapshot, may be ""
    description: str
    amount: Decimal


@dataclass(frozen=True)
class InitiationRequest:
    """Everything a provider needs to start one collection."""

    reference: UUID  # batch_id, or the payment id for a single payment
    payment_numbers: tuple[str, ...]
    demand_numbers: tuple[str, ...]
    lines: tuple[ChargeLine, ...]
    amount: Decimal  # sum of lines; equals sum of Payment.amount
    currency: str
    payer: Payer
    initiated_at: datetime  # Payment.initiated_at, never now()
    options: Mapping[str, str]  # opaque provider_options from the client
    # True when apps.payments re-runs initiate for a payment already pending
    # (spec 0017 #9.4). A provider may then skip checks that only gate NEW
    # payments (a kill switch, a cap); it must still return the same id.
    replay: bool = False


@dataclass(frozen=True)
class ActionDetail:
    """One label/value line of a ``SHOW_INSTRUCTIONS`` action."""

    key: str  # stable machine key, e.g. "reference"; lets a client add a copy button
    label: str  # human label, rendered as-is
    value: str


@dataclass(frozen=True)
class ProviderAction:
    """What the client renders, without interpreting it."""

    kind: ActionKind
    url: str = ""
    method: str = "POST"
    form_fields: Mapping[str, str] = field(default_factory=dict)
    details: tuple[ActionDetail, ...] = ()  # ordered; for SHOW_INSTRUCTIONS


@dataclass(frozen=True)
class ProviderInitiation:
    """A started collection."""

    provider_payment_id: str  # correlation id the provider echoes back
    action: ProviderAction
    metadata: dict  # non-sensitive, stored under Payment.metadata["provider"]


@dataclass(frozen=True)
class ProviderStatus:
    """A provider's authoritative view of one collection."""

    provider_payment_id: str
    outcome: ProviderOutcome
    amount: Decimal | None  # amount the provider says it collected
    provider_reference: str  # provider-issued receipt/transaction number
    paid_at: datetime | None
    failure_code: str  # provider's internal code, e.g. "EGRAS_PAYMENT_FAILED"
    failure_message: str  # safe, user-presentable
    metadata: dict  # non-sensitive
    # Provider's internal code for an anomaly an operator must review, e.g. a
    # duplicate collection; the outcome is still applied and the payment flagged.
    reconciliation_code: str = ""


@dataclass(frozen=True)
class ProviderCallback:
    """A parsed callback and whether its authenticity was proven."""

    status: ProviderStatus
    trusted: bool  # True only when the provider verified authenticity


@dataclass(frozen=True)
class PaymentOption:
    """A choice the payer makes before being sent to the provider."""

    code: str  # opaque, sent back in provider_options
    label: str
    group: str  # e.g. "NET_BANKING", "UPI"; display only


@dataclass(frozen=True)
class AttestationField:
    """One input a staff form renders for a collection method."""

    key: str  # sent back in Attestation.details
    label: str
    kind: str  # "text" | "digits" | "date"
    required: bool = True
    max_length: int = 64


@dataclass(frozen=True)
class AttestationMethod:
    """How money can be handed over to staff."""

    code: str  # opaque, e.g. "CASH"
    label: str
    fields: tuple[AttestationField, ...] = ()


@dataclass(frozen=True)
class Attestation:
    """What staff recorded, plus what ``apps.payments`` knows of the request."""

    provider_payment_id: str
    expected_amount: Decimal  # sum of Payment.amount over the group
    currency: str
    initiated_at: datetime  # earliest Payment.initiated_at of the group
    amount: Decimal  # what staff say they received
    method: str
    receipt_number: str
    collected_at: datetime
    details: Mapping[str, str]  # instrument fields keyed by AttestationField.key
    remarks: str
    # True when apps.payments records against a request that is no longer open
    # (spec 0032 #8.5); the provider then skips its recording deadline.
    late: bool = False


class ProviderError(Exception):
    """Base of every provider failure.

    ``code`` is the provider's internal failure code (stored on the payment,
    never returned by the API); ``field`` names a ``provider_options`` key when
    one is at fault.
    """

    def __init__(self, code: str, message: str = "", field: str | None = None):
        self.code = code
        self.message = message or code
        self.field = field
        super().__init__(self.message)


class ProviderPermanentError(ProviderError):
    """Retrying cannot help (bad config, unmappable charge, invalid option)."""


class ProviderTransientError(ProviderError):
    """Timeout, connection failure, 5xx or a malformed provider reply."""


class ProviderCallbackMalformed(ProviderError):  # noqa: N818 - named by spec 0017 #9.1
    """A callback payload that cannot be parsed or correlated."""


class ProviderNotConfigured(Exception):  # noqa: N818
    """Unknown provider name or unimportable path."""


class PaymentProvider(ABC):
    """A payment gateway adapter. Rules every provider honours: spec 0017 #9.2.

    Added by spec 0032 #4.1: ``attest`` is pure (it validates and maps, stores
    nothing and calls no network); an ``ATTESTED`` provider's ``fetch_status``
    never returns ``SUCCESS``; it overrides ``attest`` and
    ``attestation_methods``; and its ``parse_callback`` always raises
    ``ProviderCallbackMalformed``.
    """

    name: ClassVar[str]  # stored in Payment.provider
    label: ClassVar[str] = ""  # shown to the payer; falls back to name
    confirmation: ClassVar[ConfirmationMode] = ConfirmationMode.PROVIDER
    pending_horizon: ClassVar[timedelta]  # provider's own final-outcome window
    not_found_grace: ClassVar[timedelta]  # NOT_FOUND is final only after this

    @abstractmethod
    def list_options(self) -> list[PaymentOption]:
        """Choices the client offers the payer; empty when none is needed."""

    @abstractmethod
    def initiate(self, request: InitiationRequest) -> ProviderInitiation:
        """Start a collection. Deterministic: the same request gives the same result."""

    @abstractmethod
    def fetch_status(self, *, provider_payment_id: str) -> ProviderStatus:
        """Authoritative, side-effect-free status lookup."""

    @abstractmethod
    def parse_callback(self, payload: Mapping[str, str]) -> ProviderCallback:
        """Parse a callback; claim ``trusted`` only when authenticity was proven."""

    def attestation_methods(self) -> list[AttestationMethod]:
        """Collection methods staff may record; empty for ``PROVIDER`` providers."""

        return []

    def attest(self, attestation: Attestation) -> ProviderStatus:
        """Validate an attestation and return the status to apply.

        Raises ``ProviderPermanentError(code, message, field=<Attestation field
        or "details.<key>">)`` when the record is not acceptable.
        """

        raise ProviderPermanentError("ATTESTATION_NOT_SUPPORTED")

    def normalise_reference(self, value: str) -> str:
        """The canonical form of a reference typed by a person.

        Raises ``ProviderPermanentError`` when ``value`` cannot be one of this
        provider's references (for example, a failed check symbol).
        """

        return (value or "").strip()
