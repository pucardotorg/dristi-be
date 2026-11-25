"""eSign endpoints (spec 0015 #6).

Three JSON endpoints carry the standard ``meta`` envelope. The fourth — the ESP
callback — is a browser form POST mid-navigation, so it is unauthenticated,
CSRF-exempt and answers with a redirect instead of JSON.
"""

from urllib.parse import urlencode

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.api import errors as api_errors
from apps.api.schema import error_responses
from apps.users.services.permissions import IsAuthenticatedAndRegistered

from . import conf, constants, errors
from .exceptions import ESignError
from .log import log_event
from .models import ESignTransaction
from .parsers import ESignResponseTextXMLParser, ESignResponseXMLParser
from .serializers import (
    ClientSignatureCompleteSerializer,
    ESignInitiateSerializer,
    ESignInitiationResponseSerializer,
    ESignTransactionSerializer,
)
from .services import (
    complete_with_client_signature,
    initiate_esign,
    process_callback,
    retry_transaction,
)

FORM_METHOD = "POST"

# Failure code to HTTP status. Anything unmapped is a server-side problem. The
# JSON endpoints report failures through the codes in ``errors``, registered
# with these same statuses; the plain-text callback uses this table directly.
ERROR_STATUS = {
    constants.ESIGN_DISABLED: status.HTTP_503_SERVICE_UNAVAILABLE,
    constants.ESIGN_PROVIDER_NOT_CONFIGURED: status.HTTP_503_SERVICE_UNAVAILABLE,
    constants.ESIGN_NOT_PERMITTED: status.HTTP_403_FORBIDDEN,
    constants.ESIGN_SOURCE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    constants.ESIGN_TRANSACTION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    constants.ESIGN_INVALID_REQUEST: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_METHOD_NOT_ENABLED: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_CLIENT_SIGNATURE_MISSING: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_CLIENT_SIGNATURE_INVALID: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_CLIENT_SIGNATURE_MISMATCH: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_CERTIFICATE_NOT_PERMITTED: status.HTTP_403_FORBIDDEN,
    constants.ESIGN_NOT_A_PDF: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_INVALID_PLACEHOLDER: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_CALLBACK_MALFORMED: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_RESPONSE_UNTRUSTED: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_RESPONSE_STALE: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_NOT_RETRYABLE: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_MAX_ATTEMPTS_EXCEEDED: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_PLACEHOLDER_MISSING: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_TRANSACTION_NOT_PROCESSABLE: status.HTTP_409_CONFLICT,
    constants.ESIGN_ALREADY_IN_PROGRESS: status.HTTP_409_CONFLICT,
    constants.ESIGN_FILE_STORAGE_UNAVAILABLE: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_SIGNED_UPLOAD_FAILED: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_PDF_PREPARATION_FAILED: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_PDF_EMBED_FAILED: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_REQUEST_BUILD_FAILED: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_REQUEST_SIGNING_FAILED: status.HTTP_502_BAD_GATEWAY,
}


def initiation_payload(result) -> dict:
    """Shape an :class:`InitiationResult` as the documented response body.

    ``completion`` is read from the transaction's own provider (spec 0038 #6.1);
    ``action_url``/``payload`` are the provider-agnostic names, with
    ``esign_url``/``form_fields`` kept as aliases for one release.
    """

    from .providers import registry

    completion = registry.get(result.transaction.provider).completion
    return {
        "transaction_id": str(result.transaction.pk),
        "provider_transaction_id": result.transaction.provider_transaction_id,
        "completion": completion.name,
        "expires_at": result.transaction.expires_at,
        "action_url": result.initiation.esign_url,
        "esign_url": result.initiation.esign_url,
        "form_method": FORM_METHOD,
        "payload": dict(result.initiation.form_fields),
        "form_fields": dict(result.initiation.form_fields),
    }


class ESignInitiateView(APIView):
    """``POST /esign/_esign/`` — prepare a document and hand back the ESP form."""

    permission_classes = [IsAuthenticated, IsAuthenticatedAndRegistered]

    @extend_schema(
        operation_id="esign_initiate",
        request=ESignInitiateSerializer,
        responses={
            201: ESignInitiationResponseSerializer,
            **error_responses(
                api_errors.DOES_NOT_EXIST.example(errors.SOURCE_NOT_FOUND.message, field="file_id"),
                errors.NOT_A_PDF.example(field="file_id"),
                errors.METHOD_NOT_ENABLED,
                errors.INVALID_PLACEHOLDER,
                errors.NOT_PERMITTED,
                errors.ALREADY_IN_PROGRESS,
                errors.PDF_PREPARATION_FAILED,
                errors.FILE_STORAGE_UNAVAILABLE,
                errors.FILE_STORAGE_REJECTED,
                errors.REQUEST_BUILD_FAILED,
                errors.REQUEST_SIGNING_FAILED,
                errors.DISABLED,
                errors.PROVIDER_NOT_CONFIGURED,
            ),
        },
    )
    def post(self, request):
        """Start a signing transaction and return the form to post to the ESP."""

        serializer = ESignInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            result = initiate_esign(
                user=request.user,
                module=data["module"],
                file_id=data["file_id"],
                entity_type=data.get("entity_type") or "",
                entity_id=data.get("entity_id") or "",
                organization_id=data.get("organization_id"),
                sign_placeholder=data["sign_placeholder"],
                signing_method=data.get("signing_method") or "",
            )
        except ESignError as exc:
            raise errors.api_error(exc) from exc

        return Response(initiation_payload(result), status=status.HTTP_201_CREATED)


class ESignTransactionStatusView(APIView):
    """``GET /esign/transactions/{id}/`` — the UI's source of truth for the outcome."""

    permission_classes = [IsAuthenticated, IsAuthenticatedAndRegistered]

    @extend_schema(
        operation_id="esign_transaction_status",
        parameters=[
            OpenApiParameter(
                "transaction_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                description="eSign transaction id.",
            )
        ],
        responses=ESignTransactionSerializer,
    )
    def get(self, request, transaction_id):
        """Return the status of one of the caller's own transactions."""

        transaction = get_object_or_404(
            ESignTransaction.objects.filter(signer=request.user),
            pk=transaction_id,
        )
        return Response(ESignTransactionSerializer(transaction).data)


class ESignRetryView(APIView):
    """``POST /esign/transactions/{id}/_retry/`` — a fresh attempt at the same document."""

    permission_classes = [IsAuthenticated, IsAuthenticatedAndRegistered]

    @extend_schema(
        operation_id="esign_retry",
        request=None,
        parameters=[
            OpenApiParameter(
                "transaction_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                description="eSign transaction id to retry.",
            )
        ],
        responses={
            201: ESignInitiationResponseSerializer,
            **error_responses(
                errors.NOT_RETRYABLE,
                errors.MAX_ATTEMPTS_EXCEEDED,
                errors.PLACEHOLDER_MISSING,
                errors.NOT_PERMITTED,
                errors.ALREADY_IN_PROGRESS,
                errors.PDF_PREPARATION_FAILED,
                errors.FILE_STORAGE_UNAVAILABLE,
                errors.FILE_STORAGE_REJECTED,
                errors.REQUEST_BUILD_FAILED,
                errors.REQUEST_SIGNING_FAILED,
                errors.DISABLED,
                errors.PROVIDER_NOT_CONFIGURED,
            ),
        },
    )
    def post(self, request, transaction_id):
        """Create a new transaction from a failed or expired one."""

        parent = get_object_or_404(
            ESignTransaction.objects.filter(signer=request.user),
            pk=transaction_id,
        )
        try:
            result = retry_transaction(parent, user=request.user)
        except ESignError as exc:
            raise errors.api_error(exc) from exc

        return Response(initiation_payload(result), status=status.HTTP_201_CREATED)


class ESignMethodsView(APIView):
    """``GET /esign/methods`` — the signing methods the UI may offer (spec 0038 #6.5)."""

    permission_classes = [IsAuthenticated, IsAuthenticatedAndRegistered]

    @extend_schema(
        operation_id="esign_methods",
        responses={200: OpenApiResponse(description="Enabled signing methods.")},
    )
    def get(self, request):
        """Return the enabled methods with their completion mode."""

        from .providers import registry

        enabled = conf.enabled_methods()
        methods = []
        for name in registry.names():
            if enabled is not None and name not in set(enabled):
                continue
            try:
                provider = registry.get(name)
            except ESignError:
                continue
            methods.append({"method": name, "completion": provider.completion.name})
        return Response({"methods": methods})


class ClientSignatureCompleteView(APIView):
    """``POST /esign/transactions/{id}/_complete`` — complete from a client signature.

    The authenticated, JSON analogue of the anonymous ESP callback, and the only
    completion path for ``CLIENT_SIGNATURE`` providers (spec 0038 #6.3).
    """

    permission_classes = [IsAuthenticated, IsAuthenticatedAndRegistered]

    @extend_schema(
        operation_id="esign_complete",
        request=ClientSignatureCompleteSerializer,
        parameters=[
            OpenApiParameter(
                "transaction_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                description="eSign transaction id to complete.",
            )
        ],
        responses={
            200: ESignTransactionSerializer,
            **error_responses(
                errors.CLIENT_SIGNATURE_MISSING,
                errors.CLIENT_SIGNATURE_INVALID,
                errors.CLIENT_SIGNATURE_MISMATCH,
                errors.CERTIFICATE_NOT_PERMITTED,
                errors.RESPONSE_STALE,
                errors.TRANSACTION_NOT_PROCESSABLE,
                errors.ALREADY_IN_PROGRESS,
                errors.PDF_EMBED_FAILED,
                errors.SIGNED_UPLOAD_FAILED,
                errors.DISABLED,
            ),
        },
    )
    def post(self, request, transaction_id):
        """Verify a client-supplied signature, embed it and store the signed PDF."""

        too_large = self._reject_oversized(request)
        if too_large is not None:
            return too_large

        serializer = ClientSignatureCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        transaction = get_object_or_404(
            ESignTransaction.objects.filter(signer=request.user),
            pk=transaction_id,
        )
        try:
            outcome = complete_with_client_signature(
                transaction, serializer.validated_data["pkcs7"]
            )
        except ESignError as exc:
            raise errors.api_error(exc) from exc

        return Response(ESignTransactionSerializer(outcome.transaction).data)

    def _reject_oversized(self, request):
        """Return 413 when the body exceeds ``ESIGN_MAX_CLIENT_SIGNATURE_BYTES``."""

        limit = conf.max_client_signature_bytes()
        if not limit:
            return None
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > limit:
            return HttpResponse(
                "Payload too large.",
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content_type="text/plain; charset=utf-8",
            )
        return None


class ESignCallbackThrottle(AnonRateThrottle):
    """Per-IP throttle for the public callback (spec 0015 #6.3)."""

    scope = "esign_callback"

    def get_rate(self):
        """Return the configured rate, or ``None`` to disable throttling."""

        return conf.callback_throttle_rate() or None


@method_decorator(csrf_exempt, name="dispatch")
class ESignCallbackView(APIView):
    """``POST /esign/_signed/`` — the ESP's browser form POST.

    Trust comes from the response signature, not from the caller, so this
    endpoint is unauthenticated by necessity. It ignores every identifier in
    the request: the document and transaction come from the stored row that the
    verified response correlates to, which is what stops a caller from pointing
    a signature at another document.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [
        FormParser,
        MultiPartParser,
        ESignResponseXMLParser,
        ESignResponseTextXMLParser,
        JSONParser,
    ]
    throttle_classes = [ESignCallbackThrottle]

    @extend_schema(
        operation_id="esign_callback",
        request={"application/x-www-form-urlencoded": {"type": "object"}},
        responses={
            302: OpenApiResponse(
                description=(
                    "Redirect to the server-configured UI URL with transaction_id and "
                    "status query parameters. This endpoint is a browser form target, "
                    "not a JSON API: it carries no `meta` envelope."
                )
            ),
            400: OpenApiResponse(description="Rejected callback (plain text)."),
            413: OpenApiResponse(description="Callback body exceeds the configured limit."),
        },
    )
    def post(self, request):
        """Verify the ESP response, complete the signature and redirect."""

        too_large = self._reject_oversized(request)
        if too_large is not None:
            return too_large

        try:
            outcome = process_callback(request.data)
        except ESignError as exc:
            log_event(
                constants.EVENT_CALLBACK_REJECTED,
                None,
                failure_code=exc.code,
                **exc.audit,
            )
            if exc.transaction is not None:
                # The callback was trusted and the failure is recorded on the
                # transaction, so the browser goes back to the UI, which reads
                # the code and message from the status endpoint.
                return self._redirect(
                    transaction_id=str(exc.transaction.pk),
                    outcome_status=exc.transaction.status,
                )
            return self._rejected(exc)

        return self._redirect(
            transaction_id=str(outcome.transaction.pk),
            outcome_status=outcome.status,
        )

    # -- helpers ------------------------------------------------------------
    def _reject_oversized(self, request):
        """Return a 413 when the body exceeds the configured limit."""

        limit = conf.callback_max_body_bytes()
        if not limit:
            return None
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            declared = 0
        if declared > limit:
            log_event(
                constants.EVENT_CALLBACK_REJECTED,
                None,
                failure_code=constants.ESIGN_CALLBACK_MALFORMED,
                content_length=declared,
            )
            return HttpResponse(
                "Payload too large.",
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content_type="text/plain; charset=utf-8",
            )
        return None

    def _rejected(self, error: ESignError):
        """Answer a rejected callback without redirecting anywhere."""

        return HttpResponse(
            f"{error.code}: {error.message}",
            status=ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
            content_type="text/plain; charset=utf-8",
        )

    def _redirect(self, *, transaction_id: str, outcome_status: str):
        """Send the browser to the configured UI, or render a minimal page."""

        query = urlencode({"transaction_id": transaction_id, "status": outcome_status})
        target = conf.ui_redirect_url()
        if target:
            separator = "&" if "?" in target else "?"
            return HttpResponseRedirect(f"{target}{separator}{query}")

        # No redirect target configured: the browser still needs something to
        # render, and the status endpoint remains the client's source of truth.
        body = (
            "<!doctype html><html><head><title>Signing complete</title></head>"
            f"<body><p>Signing status: {outcome_status}</p>"
            f"<p>Transaction: {transaction_id}</p></body></html>"
        )
        return HttpResponse(body, content_type="text/html; charset=utf-8")
