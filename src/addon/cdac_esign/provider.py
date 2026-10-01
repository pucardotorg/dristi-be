"""The C-DAC eSign provider (spec 0015 #3, #7).

This is the only class ``apps.esign`` knows about, and it knows it by its
dotted path in ``ESIGN_PROVIDER``. Everything C-DAC specific — the 2.1 XML, the
ASP keystore, the response format — stops here.
"""

import base64
import logging
from collections.abc import Mapping

from django.utils import timezone

from apps.esign.exceptions import (
    ESignCallbackMalformed,
    ESignRequestBuildFailed,
    ESignRequestSigningFailed,
    ESignResponseStale,
    ESignResponseUntrusted,
    ESignSignatureInvalid,
    ESignSignatureMissing,
)
from apps.esign.providers.base import ESignInitiation, ESignProvider, ESignProviderResponse

from . import constants
from .config import resolve_config
from .keystore import CDACKeystoreError, load_key_material
from .request_builder import build_request_xml, build_transaction_id, format_timestamp
from .response_parser import (
    SIGNATURE_INVALID,
    SIGNATURE_MISSING,
    CDACResponseMalformed,
    ParsedCDACResponse,
    extract_response_document,
    parse_response_xml,
)
from .response_verifier import (
    CDACResponseStale,
    CDACResponseUntrusted,
    check_timestamp_freshness,
    verify_response_signature,
)
from .xml_signer import CDACXMLSigningError, sign_request_xml

logger = logging.getLogger("addon.cdac_esign")


class CDACESignProvider(ESignProvider):
    """Speaks eSign API 2.1 to the C-DAC ESP."""

    name = constants.PROVIDER_NAME

    def build_initiation(self, transaction, document_hash: str) -> ESignInitiation:
        """Build, sign and base64-encode the ``<Esign>`` request."""

        config = resolve_config()
        provider_transaction_id = build_transaction_id(
            config,
            module=transaction.module,
            transaction_id=str(transaction.pk),
        )
        timestamp = timezone.now()

        try:
            xml = build_request_xml(
                config,
                transaction_id=provider_transaction_id,
                document_hash=document_hash,
                doc_info=self._doc_info(transaction),
                timestamp=timestamp,
            )
        except (ValueError, TypeError) as exc:
            raise ESignRequestBuildFailed() from exc

        try:
            key_material = load_key_material(config.keystore_path, config.keystore_password)
            signed_xml = sign_request_xml(xml, key_material)
        except (CDACKeystoreError, CDACXMLSigningError) as exc:
            # The message may name a path or a key; only the safe default text
            # is allowed to travel further.
            logger.error("event='CDAC_REQUEST_SIGNING_FAILED' reason=%r", str(exc))
            raise ESignRequestSigningFailed() from exc

        return ESignInitiation(
            esign_url=config.url,
            form_fields={
                constants.FORM_FIELD_REQUEST: base64.b64encode(signed_xml).decode(),
                constants.FORM_FIELD_ASP_TXN: provider_transaction_id,
                constants.FORM_FIELD_CONTENT_TYPE: constants.FORM_CONTENT_TYPE,
            },
            provider_transaction_id=provider_transaction_id,
            request_audit={
                "provider": self.name,
                "version": config.version,
                "auth_mode": config.auth_mode,
                "hash_algorithm": config.hash_algorithm,
                "ekyc_id_type": config.ekyc_id_type,
                "consent": config.consent,
                "response_sig_type": constants.RESPONSE_SIG_TYPE,
                "requested_at": format_timestamp(timestamp),
                "asp_id": config.asp_id,
                "input_hash_count": constants.EXPECTED_SIGNATURE_COUNT,
            },
        )

    def parse_response(self, payload: Mapping[str, str]) -> ESignProviderResponse:
        """Turn an ``<EsignResp>`` document into the domain's response shape."""

        config = resolve_config()
        try:
            document = extract_response_document(payload, config)
            parsed = parse_response_xml(document)
        except CDACResponseMalformed as exc:
            raise ESignCallbackMalformed() from exc

        return ESignProviderResponse(
            provider_transaction_id=parsed.transaction_id,
            success=parsed.success,
            signature=parsed.signature,
            signer_certificate=parsed.signer_certificate,
            error_code="" if parsed.success else self._failure_code(parsed),
            error_message="" if parsed.success else parsed.error_message,
            signed_at=parsed.timestamp,
            response_audit=self._response_audit(parsed),
        )

    def verify_response(self, payload: Mapping[str, str]) -> None:
        """Verify the response signature and its freshness."""

        config = resolve_config()
        try:
            document = extract_response_document(payload, config)
        except CDACResponseMalformed as exc:
            raise ESignCallbackMalformed() from exc

        if config.verify_response_signature:
            try:
                verify_response_signature(document, config.response_cert)
            except CDACResponseUntrusted as exc:
                logger.warning("event='CDAC_RESPONSE_UNTRUSTED' reason=%r", str(exc))
                raise ESignResponseUntrusted() from exc
        else:
            logger.warning(
                "event='CDAC_RESPONSE_VERIFICATION_DISABLED' "
                "detail='response signature not checked'"
            )

        try:
            parsed = parse_response_xml(document)
        except CDACResponseMalformed as exc:
            raise ESignCallbackMalformed() from exc

        try:
            check_timestamp_freshness(
                parsed.timestamp,
                max_skew_seconds=config.response_max_skew,
            )
        except CDACResponseStale as exc:
            raise ESignResponseStale() from exc

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _failure_code(parsed: ParsedCDACResponse) -> str:
        """Map a failed response onto an internal failure code.

        A signature that is absent or unusable is reported precisely; every
        other ``errCode`` maps through the addon's table so the domain never
        sees a C-DAC code.
        """

        if parsed.signature_error == SIGNATURE_MISSING:
            return ESignSignatureMissing.code
        if parsed.signature_error == SIGNATURE_INVALID:
            return ESignSignatureInvalid.code
        return constants.map_error_code(parsed.error_code)

    @staticmethod
    def _doc_info(transaction) -> str:
        """Short, non-sensitive description of what is being signed."""

        parts = [part for part in (transaction.entity_type, transaction.entity_id) if part]
        return " ".join(parts) or transaction.module or str(transaction.pk)

    @staticmethod
    def _response_audit(parsed: ParsedCDACResponse) -> dict:
        """Audit metadata for a response: codes and certificate metadata only."""

        audit = {
            "provider": constants.PROVIDER_NAME,
            "status": parsed.status,
            "result_code": parsed.result_code,
            "provider_error_code": parsed.error_code,
            "signature_count": parsed.signature_count,
            "signature_error": parsed.signature_error,
        }
        audit.update(parsed.certificate_audit)
        return audit
