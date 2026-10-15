"""The ESP contract every provider implements (spec 0015 #3).

An implementation may live anywhere — ``addon.cdac_esign`` holds the C-DAC one —
and is selected purely by the ``ESIGN_PROVIDER`` setting. Providers receive an
``ESignTransaction`` (possibly not yet saved, so they must only read fields) and
return plain dataclasses; they never touch the database, the PDF Service or the
File Storage Service.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar


@dataclass(frozen=True)
class ESignInitiation:
    """Everything the browser needs to hand the document off to the ESP."""

    esign_url: str
    form_fields: dict[str, str]
    provider_transaction_id: str
    request_audit: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ESignProviderResponse:
    """The outcome of a signing attempt as reported by the ESP."""

    provider_transaction_id: str
    success: bool
    signature: str | None = None
    signer_certificate: str | None = None
    error_code: str = ""
    error_message: str = ""
    signed_at: datetime | None = None
    response_audit: dict = field(default_factory=dict)


class ESignProvider(ABC):
    """Abstract ESP adapter."""

    name: ClassVar[str]

    @abstractmethod
    def build_initiation(self, transaction, document_hash: str) -> ESignInitiation:
        """Return the ESP endpoint and form fields for this transaction."""

    @abstractmethod
    def parse_response(self, payload: Mapping[str, str]) -> ESignProviderResponse:
        """Turn a raw callback payload into an :class:`ESignProviderResponse`.

        Raise ``ESignCallbackMalformed`` when the payload cannot be read.
        """

    @abstractmethod
    def verify_response(self, payload: Mapping[str, str]) -> None:
        """Raise ``ESignResponseUntrusted`` if the ESP response is not authentic."""
