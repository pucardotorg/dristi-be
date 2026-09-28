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
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.users.services.permissions import IsAuthenticatedAndRegistered

from . import conf, constants
from .exceptions import ESignError
from .log import log_event
from .models import ESignTransaction
from .parsers import ESignResponseTextXMLParser, ESignResponseXMLParser
from .serializers import (
    ESignErrorSerializer,
    ESignInitiateSerializer,
    ESignInitiationResponseSerializer,
    ESignTransactionSerializer,
)
from .services import initiate_esign, process_callback, retry_transaction

TAGS = ["esign"]
FORM_METHOD = "POST"

# Failure code to HTTP status. Anything unmapped is a server-side problem.
ERROR_STATUS = {
    constants.ESIGN_DISABLED: status.HTTP_503_SERVICE_UNAVAILABLE,
    constants.ESIGN_PROVIDER_NOT_CONFIGURED: status.HTTP_503_SERVICE_UNAVAILABLE,
    constants.ESIGN_NOT_PERMITTED: status.HTTP_403_FORBIDDEN,
    constants.ESIGN_SOURCE_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    constants.ESIGN_TRANSACTION_NOT_FOUND: status.HTTP_404_NOT_FOUND,
    constants.ESIGN_INVALID_REQUEST: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_NOT_A_PDF: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_INVALID_PLACEHOLDER: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_CALLBACK_MALFORMED: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_RESPONSE_UNTRUSTED: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_RESPONSE_STALE: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_NOT_RETRYABLE: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_MAX_ATTEMPTS_EXCEEDED: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_PLACEHOLDER_MISSING: status.HTTP_400_BAD_REQUEST,
    constants.ESIGN_TRANSACTION_NOT_PROCESSABLE: status.HTTP_409_CONFLICT,
    constants.ESIGN_FILE_STORAGE_UNAVAILABLE: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_SIGNED_UPLOAD_FAILED: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_PDF_PREPARATION_FAILED: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_PDF_EMBED_FAILED: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_REQUEST_BUILD_FAILED: status.HTTP_502_BAD_GATEWAY,
    constants.ESIGN_REQUEST_SIGNING_FAILED: status.HTTP_502_BAD_GATEWAY,
}


def error_response(error: ESignError) -> Response:
    """Return the standard error body for a domain failure."""

    return Response(
        {"code": error.code, "detail": error.message},
        status=ERROR_STATUS.get(error.code, status.HTTP_500_INTERNAL_SERVER_ERROR),
    )


def initiation_payload(result) -> dict:
    """Shape an :class:`InitiationResult` as the documented response body."""

    return {
        "transaction_id": str(result.transaction.pk),
        "provider_transaction_id": result.transaction.provider_transaction_id,
        "expires_at": result.transaction.expires_at,
        "esign_url": result.initiation.esign_url,
        "form_method": FORM_METHOD,
        "form_fields": dict(result.initiation.form_fields),
    }


class ESignInitiateView(APIView):
    """``POST /esign/_esign`` — prepare a document and hand back the ESP form."""

    permission_classes = [IsAuthenticated, IsAuthenticatedAndRegistered]

    @extend_schema(
        tags=TAGS,
        operation_id="esign_initiate",
        request=ESignInitiateSerializer,
        responses={
            201: ESignInitiationResponseSerializer,
            400: OpenApiResponse(ESignErrorSerializer, "Invalid request or placement."),
            403: OpenApiResponse(ESignErrorSerializer, "Not permitted to sign this entity."),
            503: OpenApiResponse(ESignErrorSerializer, "eSign is disabled or unconfigured."),
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
            )
        except ESignError as exc:
            return error_response(exc)

        return Response(initiation_payload(result), status=status.HTTP_201_CREATED)


class ESignTransactionStatusView(APIView):
    """``GET /esign/transactions/{id}`` — the UI's source of truth for the outcome."""

    permission_classes = [IsAuthenticated, IsAuthenticatedAndRegistered]

    @extend_schema(
        tags=TAGS,
        operation_id="esign_transaction_status",
        parameters=[
            OpenApiParameter(
                "id",
                str,
                OpenApiParameter.PATH,
                description="eSign transaction id.",
            )
        ],
        responses={
            200: ESignTransactionSerializer,
            404: OpenApiResponse(ESignErrorSerializer, "Unknown transaction."),
        },
    )
    def get(self, request, transaction_id):
        """Return the status of one of the caller's own transactions."""

        transaction = get_object_or_404(
            ESignTransaction.objects.filter(signer=request.user),
            pk=transaction_id,
        )
        return Response(ESignTransactionSerializer(transaction).data)


class ESignRetryView(APIView):
    """``POST /esign/transactions/{id}/_retry`` — a fresh attempt at the same document."""

    permission_classes = [IsAuthenticated, IsAuthenticatedAndRegistered]

    @extend_schema(
        tags=TAGS,
        operation_id="esign_retry",
        request=None,
        parameters=[
            OpenApiParameter(
                "id",
                str,
                OpenApiParameter.PATH,
                description="eSign transaction id to retry.",
            )
        ],
        responses={
            201: ESignInitiationResponseSerializer,
            400: OpenApiResponse(ESignErrorSerializer, "Not retryable or attempts exhausted."),
            404: OpenApiResponse(ESignErrorSerializer, "Unknown transaction."),
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
            return error_response(exc)

        return Response(initiation_payload(result), status=status.HTTP_201_CREATED)


class ESignCallbackThrottle(AnonRateThrottle):
    """Per-IP throttle for the public callback (spec 0015 #6.3)."""

    scope = "esign_callback"

    def get_rate(self):
        """Return the configured rate, or ``None`` to disable throttling."""

        return conf.callback_throttle_rate() or None


@method_decorator(csrf_exempt, name="dispatch")
class ESignCallbackView(APIView):
    """``POST /esign/_signed`` — the ESP's browser form POST.

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
        tags=TAGS,
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
            413: OpenApiResponse(description="Payload too large (plain text)."),
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
