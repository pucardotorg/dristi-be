"""The DSC eSign provider (spec 0038 #3, #7).

A ``CLIENT_SIGNATURE`` provider. ``build_initiation`` hands the browser the local
agent URL and the digest to sign; the agent returns a detached PKCS#7 that the
authenticated ``_complete`` endpoint feeds to ``verify_client_signature``. The
callback methods raise, because DSC is never completed by the anonymous ESP
callback — so an anonymous POST can never complete a DSC transaction.
"""

from collections.abc import Mapping

from apps.esign.exceptions import ESignCallbackMalformed, ESignResponseUntrusted
from apps.esign.providers.base import (
    Completion,
    ESignInitiation,
    ESignProvider,
    ESignProviderResponse,
)

from . import constants
from .config import resolve_config
from .verify import verify_client_signature


class DSCESignProvider(ESignProvider):
    """Signs with the signatory's own DSC token via a local pyHanko agent."""

    name = constants.PROVIDER_NAME
    completion = Completion.CLIENT_SIGNATURE

    def build_initiation(self, transaction, document_hash: str) -> ESignInitiation:
        """Return the local-agent URL and the digest payload to sign."""

        config = resolve_config()
        provider_transaction_id = f"{constants.TRANSACTION_ID_PREFIX}-{transaction.pk}"[
            : constants.MAX_TRANSACTION_ID_LENGTH
        ]
        payload = {
            constants.FORM_FIELD_DIGEST: document_hash,
            constants.FORM_FIELD_HASH_ALGORITHM: config.hash_algorithm.lower(),
            constants.FORM_FIELD_FIELD_NAME: transaction.signature_field_name,
            constants.FORM_FIELD_TRANSACTION_ID: str(transaction.pk),
        }
        payload.update(self._placement_hints(transaction.sign_placeholder or {}))

        return ESignInitiation(
            esign_url=config.agent_url,
            form_fields=payload,
            provider_transaction_id=provider_transaction_id,
            request_audit={"provider": self.name, "hash_algorithm": config.hash_algorithm},
        )

    def parse_response(self, payload: Mapping[str, str]) -> ESignProviderResponse:
        """DSC never completes through the anonymous callback."""

        raise ESignCallbackMalformed("DSC transactions are not completed by the ESP callback.")

    def verify_response(self, payload: Mapping[str, str]) -> None:
        """DSC never completes through the anonymous callback."""

        raise ESignResponseUntrusted("DSC transactions are not completed by the ESP callback.")

    def verify_client_signature(self, transaction, pkcs7: bytes) -> ESignProviderResponse:
        """Verify the token's detached PKCS#7 against the prepared document."""

        return verify_client_signature(transaction, pkcs7, resolve_config())

    @staticmethod
    def _placement_hints(placeholder: dict) -> dict:
        """Non-authoritative placement hints for the agent's log/appearance."""

        hints = {}
        page = placeholder.get("page")
        if page is not None:
            hints["page"] = str(page)
        x, y = placeholder.get("x"), placeholder.get("y")
        if x is not None and y is not None:
            hints["cood"] = f"{x},{y}"
        width, height = placeholder.get("width"), placeholder.get("height")
        if width is not None and height is not None:
            hints["size"] = f"{width},{height}"
        return hints
