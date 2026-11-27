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
from enum import Flag, auto
from typing import ClassVar


class Completion(Flag):
    """How a provider's transaction is completed (spec 0038 #3).

    ``CALLBACK`` providers finish through the anonymous ESP callback
    (``/esign/_signed``); ``CLIENT_SIGNATURE`` providers finish through the
    authenticated ``_complete`` endpoint, where the signer's own client posts a
    signature. The two completion endpoints branch on this capability, never on
    a provider name, so the anonymous callback can never complete a
    client-signature transaction.
    """

    CALLBACK = auto()
    CLIENT_SIGNATURE = auto()


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
    # Most providers finish through the anonymous ESP callback; a provider that
    # completes from the signer's own client overrides this to CLIENT_SIGNATURE.
    completion: ClassVar[Completion] = Completion.CALLBACK

    @abstractmethod
    def build_initiation(self, transaction, document_hash: str) -> ESignInitiation:
        """Return the ESP endpoint and form fields for this transaction."""

    @abstractmethod
    def parse_response(self, payload: Mapping[str, str]) -> ESignProviderResponse:
        """Turn a raw callback payload into an :class:`ESignProviderResponse`.

        Raise ``ESignCallbackMalformed`` when the payload cannot be read.
        ``CLIENT_SIGNATURE`` providers must raise here — they never parse a
        callback — so the anonymous endpoint cannot be used to complete them.
        """

    @abstractmethod
    def verify_response(self, payload: Mapping[str, str]) -> None:
        """Raise ``ESignResponseUntrusted`` if the ESP response is not authentic.

        ``CLIENT_SIGNATURE`` providers must raise here; the anonymous callback's
        only trust gate is this method, so a no-op would let an anonymous POST
        complete the transaction.
        """

    def verify_client_signature(self, transaction, pkcs7: bytes) -> ESignProviderResponse:
        """Verify a client-supplied detached PKCS#7 against ``transaction`` (spec 0038 #8.1).

        Implemented only by ``CLIENT_SIGNATURE`` providers; it binds the CMS to
        the prepared document, verifies the signature, and applies the
        provider's certificate policy. The default refuses, so a ``CALLBACK``
        provider can never be completed through the authenticated endpoint.
        """

        raise NotImplementedError(
            f"{type(self).__name__} does not complete from a client signature."
        )
