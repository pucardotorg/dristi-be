"""A provider that needs no ESP credentials — the local/test default (spec 0015 #3).

It performs no cryptography: ``verify_response`` trusts whatever it is given,
which is exactly why the production system checks refuse to let it be the
active provider.
"""

import base64
from collections.abc import Mapping
from datetime import datetime

from django.utils import timezone

from ..exceptions import ESignCallbackMalformed, ESignSignatureMissing
from .base import ESignInitiation, ESignProvider, ESignProviderResponse

# Unroutable by design: the mock ESP is never actually contacted.
MOCK_ESIGN_URL = "https://esign.mock.invalid/esign"
MAX_TRANSACTION_ID_LENGTH = 128


class MockESignProvider(ESignProvider):
    """Echoes the request back as form fields a test client can post."""

    name = "mock"

    def build_initiation(self, transaction, document_hash: str) -> ESignInitiation:
        """Return a form that posts the hash straight back to the callback."""

        provider_transaction_id = f"{transaction.module}-{transaction.pk}"[
            :MAX_TRANSACTION_ID_LENGTH
        ]
        request = f"{provider_transaction_id}:{document_hash}".encode()
        return ESignInitiation(
            esign_url=MOCK_ESIGN_URL,
            form_fields={
                "eSignRequest": base64.b64encode(request).decode(),
                "aspTxnID": provider_transaction_id,
                "Content-Type": "application/xml",
            },
            provider_transaction_id=provider_transaction_id,
            request_audit={
                "provider": self.name,
                "hash_algorithm": "SHA256",
                "requested_at": timezone.now().isoformat(),
            },
        )

    def parse_response(self, payload: Mapping[str, str]) -> ESignProviderResponse:
        """Read the flat form payload the mock ESP posts back."""

        provider_transaction_id = (payload.get("txn") or "").strip()
        if not provider_transaction_id:
            raise ESignCallbackMalformed("The callback payload carries no transaction id.")

        status = (payload.get("status") or "").strip()
        signature = (payload.get("signature") or "").strip() or None
        error_code = (payload.get("errCode") or "").strip()
        success = status == "1" and signature is not None
        if status == "1" and signature is None:
            # Mirrors the real provider: a success with no signature is a
            # precise failure the domain can record and offer a retry for.
            error_code = ESignSignatureMissing.code

        return ESignProviderResponse(
            provider_transaction_id=provider_transaction_id,
            success=success,
            signature=signature,
            signer_certificate=(payload.get("certificate") or "").strip() or None,
            error_code="" if success else (error_code or "MOCK_FAILURE"),
            error_message=(payload.get("errMsg") or "").strip(),
            signed_at=self._parse_timestamp(payload.get("ts")),
            response_audit={"provider": self.name, "status": status, "error_code": error_code},
        )

    def verify_response(self, payload: Mapping[str, str]) -> None:
        """Accept every payload; the mock ESP signs nothing."""

    @staticmethod
    def _parse_timestamp(value) -> datetime | None:
        """Return ``value`` as an aware datetime, or ``None`` when unusable."""

        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if timezone.is_naive(parsed):
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
