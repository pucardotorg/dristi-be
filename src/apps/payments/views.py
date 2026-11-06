"""Demand and payment endpoints (spec 0017 #12).

Views validate input, call a service and serialize the result. Every queryset
comes from ``selectors``, already narrowed to what the caller may see, so a
record on someone else's case is a 404. The provider callback is the one
public endpoint: a browser form target that redirects instead of returning JSON.
"""

import logging
from urllib.parse import urlencode

from django.core.cache import cache
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from apps.api.errors import BusinessError
from apps.api.schema import error_responses

from . import access, conf, errors, selectors
from .enums import DemandStatus, ReferenceType
from .models import DemandItem, Payment
from .providers import registry
from .providers.base import ProviderError, ProviderNotConfigured
from .serializers import (
    BatchCreateSerializer,
    BatchSerializer,
    CancelSerializer,
    DemandSerializer,
    PaymentCreatedSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    ProviderOptionsSerializer,
    batch_payload,
)
from .services import DemandService, PaymentService

logger = logging.getLogger(__name__)

UUID_REGEX = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
IDEMPOTENCY_HEADER = "HTTP_IDEMPOTENCY_KEY"
OPTIONS_CACHE_SECONDS = 300
CALLBACK_UNKNOWN = "UNKNOWN"


def with_client_request_id(request) -> dict:
    """The request body, with ``Idempotency-Key`` mapped onto ``client_request_id``."""

    data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
    header = request.META.get(IDEMPOTENCY_HEADER, "").strip()
    if header and not data.get("client_request_id"):
        data["client_request_id"] = header
    return data


IDEMPOTENCY_PARAMETER = OpenApiParameter(
    "Idempotency-Key",
    OpenApiTypes.STR,
    OpenApiParameter.HEADER,
    required=False,
    description="Alternative to `client_request_id` in the body; same meaning (spec 0017 #7).",
)

PAYMENT_CREATION_ERRORS = (
    errors.DEMAND_NOT_PAYABLE,
    errors.ITEM_NOT_PAYABLE.example(field="demand_item_ids[0]"),
    errors.ITEM_NOT_IN_DEMAND.example(field="demand_item_ids[0]"),
    errors.DUPLICATE_DEMAND_ITEM.example(field="demand_item_ids[1]"),
    errors.PAYMENT_IN_FLIGHT.example(field="demand_item_ids[0]"),
    errors.CLIENT_REQUEST_ID_REUSED.example(field="client_request_id"),
    errors.PROVIDER_REJECTED,
    errors.PROVIDER_UNAVAILABLE,
    errors.PROVIDER_REPLAY_MISMATCH,
    errors.PROVIDER_OPTION_INVALID.example(field="provider_options.bank"),
)


class DemandFilterSerializer(serializers.Serializer):
    """Query parameters of the demand list."""

    case_id = serializers.UUIDField(required=False)
    reference_type = serializers.ChoiceField(choices=ReferenceType.choices, required=False)
    reference_id = serializers.CharField(max_length=64, required=False)
    status = serializers.ChoiceField(choices=DemandStatus.choices, required=False)
    organization_id = serializers.UUIDField(required=False)


@extend_schema_view(
    list=extend_schema(parameters=[DemandFilterSerializer]),
    cancel=extend_schema(
        request=CancelSerializer,
        responses={
            200: DemandSerializer,
            **error_responses(errors.DEMAND_NOT_CANCELLABLE, errors.NOT_DEMAND_CREATOR),
        },
    ),
    cancel_item=extend_schema(
        request=CancelSerializer,
        parameters=[OpenApiParameter("item_id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        responses={
            200: DemandSerializer,
            **error_responses(errors.ITEM_NOT_CANCELLABLE, errors.NOT_DEMAND_CREATOR),
        },
    ),
    payments=extend_schema(responses=PaymentSerializer),
)
class DemandViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """List, retrieve and cancel demands; pay and list their payments.

    There is no create: demands are raised in-process by the raising modules
    through ``DemandService.raise_demand`` (spec 0017 #13).
    """

    serializer_class = DemandSerializer
    lookup_url_kwarg = "demand_id"
    lookup_value_regex = UUID_REGEX
    list_actions = {"payments"}

    def get_queryset(self):
        """Demands the caller may see, filtered by the query parameters."""

        queryset = selectors.demands_for(self.request.user)
        if self.action != "list":
            return queryset
        filters = DemandFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return queryset.filter(**filters.validated_data)

    def get_serializer_class(self):
        """Pick the serializer for the action."""

        if self.action in ("cancel", "cancel_item"):
            return CancelSerializer
        if self.action == "payments":
            return PaymentSerializer
        if self.action == "create_payment":
            return PaymentCreateSerializer
        return DemandSerializer

    @staticmethod
    def _require_creator(request, demand):
        """Only the user who raised a demand may cancel it over REST (spec 0017 #13).

        Demands raised in-process are cancelled by their raising module in code.
        """

        if demand.created_by_id is None or demand.created_by_id != request.user.pk:
            raise BusinessError(errors.NOT_DEMAND_CREATOR)

    def _demand_response(self, demand, status_code=status.HTTP_200_OK):
        demand = selectors.demands_for(self.request.user).get(pk=demand.pk)
        return Response(DemandSerializer(demand).data, status=status_code)

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        """Cancel a demand nothing has been paid against."""

        demand = self.get_object()
        self._require_creator(request, demand)
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DemandService.cancel_demand(
            demand, reason=serializer.validated_data["reason"], actor=request.user
        )
        return self._demand_response(demand)

    @action(
        detail=True,
        methods=["post"],
        url_path=rf"items/(?P<item_id>{UUID_REGEX})/cancel",
        url_name="cancel-item",
    )
    def cancel_item(self, request, *args, item_id=None, **kwargs):
        """Cancel one unpaid line item."""

        demand = self.get_object()
        item = get_object_or_404(DemandItem.objects.filter(demand=demand), pk=item_id)
        self._require_creator(request, demand)
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        DemandService.cancel_item(
            item, reason=serializer.validated_data["reason"], actor=request.user
        )
        return self._demand_response(demand)

    @action(detail=True, methods=["get"])
    def payments(self, request, *args, **kwargs):
        """Payment history of a demand, newest first."""

        demand = self.get_object()
        queryset = selectors.payments_for(request.user).filter(demand=demand)
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(PaymentSerializer(page, many=True).data)

    @payments.mapping.post
    @extend_schema(
        request=PaymentCreateSerializer,
        parameters=[IDEMPOTENCY_PARAMETER],
        responses={
            201: PaymentCreatedSerializer,
            200: OpenApiResponse(
                PaymentCreatedSerializer,
                description="Replay of an earlier request with the same client_request_id.",
            ),
            **error_responses(*PAYMENT_CREATION_ERRORS),
        },
    )
    def create_payment(self, request, *args, **kwargs):
        """Pay one item, a subset, or every payable item of a demand."""

        demand = self.get_object()
        serializer = PaymentCreateSerializer(data=with_client_request_id(request))
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        collection = PaymentService.create_payment(
            demand=demand,
            demand_item_ids=data["demand_item_ids"],
            client_request_id=data["client_request_id"],
            payer=data.get("payer"),
            provider_options=data.get("provider_options"),
            payment_mode=data.get("payment_mode", ""),
            actor=request.user,
        )
        payment = selectors.payments_for(request.user).get(pk=collection.payment.pk)
        body = PaymentCreatedSerializer(
            payment, context={"provider_action": collection.action}
        ).data
        return Response(
            body, status=status.HTTP_201_CREATED if collection.created else status.HTTP_200_OK
        )


@extend_schema_view(
    cancel=extend_schema(
        request=CancelSerializer,
        responses={
            200: PaymentSerializer,
            **error_responses(
                errors.PAYMENT_NOT_CANCELLABLE,
                errors.PAYMENT_OUTCOME_PENDING,
                errors.PAYMENT_ALREADY_COMPLETED,
                errors.NOT_PAYMENT_CREATOR,
                errors.PROVIDER_UNAVAILABLE,
            ),
        },
    ),
)
class PaymentViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Retrieve a payment (the client's source of truth) and cancel it."""

    serializer_class = PaymentSerializer
    lookup_url_kwarg = "payment_id"
    lookup_value_regex = UUID_REGEX

    def get_queryset(self):
        """Payments the caller may see."""

        return selectors.payments_for(self.request.user)

    def get_serializer_class(self):
        """Pick the serializer for the action."""

        return CancelSerializer if self.action == "cancel" else PaymentSerializer

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        """Cancel a non-terminal payment (the whole batch, if it is in one)."""

        payment = self.get_object()
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        PaymentService.request_cancellation(
            payment, actor=request.user, reason=serializer.validated_data["reason"]
        )
        payment = self.get_queryset().get(pk=payment.pk)
        return Response(PaymentSerializer(payment).data)


@extend_schema_view(
    create=extend_schema(
        request=BatchCreateSerializer,
        parameters=[IDEMPOTENCY_PARAMETER],
        responses={
            201: BatchSerializer,
            200: OpenApiResponse(
                BatchSerializer,
                description="Replay of an earlier request with the same client_request_id.",
            ),
            **error_responses(
                *PAYMENT_CREATION_ERRORS,
                errors.CURRENCY_MISMATCH,
                errors.BATCH_TOO_LARGE.example(field="selections"),
                errors.DEMAND_REPEATED_IN_BATCH.example(field="selections[1].demand_id"),
            ),
        },
    ),
    retrieve=extend_schema(
        parameters=[OpenApiParameter("batch_id", OpenApiTypes.UUID, OpenApiParameter.PATH)],
        responses=BatchSerializer,
    ),
)
class BatchViewSet(viewsets.GenericViewSet):
    """Pay across several demands in one provider transaction."""

    serializer_class = BatchSerializer
    lookup_url_kwarg = "batch_id"
    lookup_value_regex = UUID_REGEX

    def get_queryset(self):
        """Payments the caller may see."""

        return selectors.payments_for(self.request.user)

    def get_serializer_class(self):
        """Pick the serializer for the action."""

        return BatchCreateSerializer if self.action == "create" else BatchSerializer

    def create(self, request, *args, **kwargs):
        """Create one payment per selected demand, sharing a batch id."""

        serializer = BatchCreateSerializer(data=with_client_request_id(request))
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        visible = access.visible_demands(request.user)
        selections = []
        for selection in data["selections"]:
            demand = visible.filter(pk=selection["demand_id"]).first()
            if demand is None:
                # One demand the caller cannot see rejects the whole batch.
                raise NotFound()
            selections.append({"demand": demand, "demand_item_ids": selection["demand_item_ids"]})

        collection = PaymentService.create_batch(
            selections=selections,
            client_request_id=data["client_request_id"],
            payer=data.get("payer"),
            provider_options=data.get("provider_options"),
            payment_mode=data.get("payment_mode", ""),
            actor=request.user,
        )
        payments = selectors.batch_payments(request.user, collection.batch_id)
        return Response(
            BatchSerializer(batch_payload(payments, collection.action)).data,
            status=status.HTTP_201_CREATED if collection.created else status.HTTP_200_OK,
        )

    def retrieve(self, request, *args, batch_id=None, **kwargs):
        """The payments of one batch."""

        payments = selectors.batch_payments(request.user, batch_id)
        if not payments:
            raise NotFound()
        return Response(BatchSerializer(batch_payload(payments)).data)


class ProviderOptionsView(APIView):
    """``GET /payments/providers/options/`` — the default provider's choices."""

    @extend_schema(
        operation_id="payments_provider_options",
        responses={200: ProviderOptionsSerializer, **error_responses(errors.PROVIDER_UNAVAILABLE)},
    )
    def get(self, request):
        """Options to render a bank/UPI picker without knowing the provider."""

        try:
            provider = registry.get_default()
        except ProviderNotConfigured as exc:
            raise BusinessError(errors.PROVIDER_UNAVAILABLE) from exc
        if provider is None:
            return Response({"provider": "", "options": []})

        key = f"payments:provider-options:{provider.name}"
        options = cache.get(key)
        if options is None:
            try:
                options = [
                    {"code": option.code, "label": option.label, "group": option.group}
                    for option in provider.list_options()
                ]
            except ProviderError as exc:
                raise BusinessError(errors.PROVIDER_UNAVAILABLE) from exc
            cache.set(key, options, OPTIONS_CACHE_SECONDS)
        return Response(
            ProviderOptionsSerializer({"provider": provider.name, "options": options}).data
        )


class PaymentCallbackThrottle(AnonRateThrottle):
    """Per-IP throttle for the public callback (spec 0017 #9.6)."""

    scope = "payments_callback"

    def get_rate(self):
        """The configured rate, or ``None`` to disable throttling."""

        return conf.callback_throttle_rate() or None


@method_decorator(csrf_exempt, name="dispatch")
class ProviderCallbackView(APIView):
    """``POST /payments/providers/{provider}/_callback`` — a provider's browser return.

    Trust comes from verification, not from the caller: an unverified callback
    only selects which payment to ask the provider about. The response is
    always a redirect to the server-configured UI; the client then reads
    ``GET /payments/payments/{id}/``, the only source of truth.
    """

    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser, MultiPartParser, JSONParser]
    throttle_classes = [PaymentCallbackThrottle]

    @extend_schema(
        operation_id="payments_provider_callback",
        request={"application/x-www-form-urlencoded": {"type": "object"}},
        parameters=[OpenApiParameter("provider", OpenApiTypes.STR, OpenApiParameter.PATH)],
        responses={
            302: OpenApiResponse(
                description=(
                    "Redirect to PAYMENT_UI_REDIRECT_URL with `payment_id` (or `batch_id`) "
                    "and the local `status` (UNKNOWN when the callback matched no payment). "
                    "A browser form target, not a JSON API: no `meta` envelope."
                )
            ),
        },
    )
    def post(self, request, provider):
        """Verify the outcome with the provider, apply it, redirect the browser."""

        if provider not in registry.names():
            raise NotFound()

        if self._too_large(request):
            return self._redirect(status_value=CALLBACK_UNKNOWN)

        try:
            adapter = registry.get(provider)
            callback = adapter.parse_callback(self._payload(request))
        except (ProviderError, ProviderNotConfigured, ParseError, ValueError) as exc:
            logger.warning("Rejected %s payment callback: %s", provider, exc)
            return self._redirect(status_value=CALLBACK_UNKNOWN)
        except Exception:  # noqa: BLE001 - the browser is always sent back (#12.5)
            logger.exception("The %s provider failed to parse a callback.", provider)
            return self._redirect(status_value=CALLBACK_UNKNOWN)

        provider_payment_id = callback.status.provider_payment_id
        payments = []
        if provider_payment_id:
            payments = list(
                Payment.objects.filter(
                    provider=provider, provider_payment_id=provider_payment_id
                ).order_by("pk")
            )
        if not payments:
            return self._redirect(status_value=CALLBACK_UNKNOWN)

        status_ = callback.status
        if not callback.trusted:
            try:
                status_ = adapter.fetch_status(provider_payment_id=provider_payment_id)
            except Exception as exc:  # noqa: BLE001 - the poller finishes the job (#9.7)
                if isinstance(exc, ProviderError):
                    logger.warning("Could not verify %s callback: %s", provider, exc.code)
                else:
                    logger.exception("The %s provider failed to verify a callback.", provider)
                return self._redirect_for(payments)

        try:
            PaymentService.apply_provider_status(payments, status_)
        except Exception:  # noqa: BLE001 - always redirect (#12.5); the poller retries (#9.7)
            logger.exception("Could not apply the %s callback outcome.", provider)
        return self._redirect_for(payments)

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _payload(request) -> dict[str, str]:
        data = request.data
        if hasattr(data, "dict"):
            data = data.dict()
        return {str(key): "" if value is None else str(value) for key, value in data.items()}

    @staticmethod
    def _too_large(request) -> bool:
        limit = conf.callback_max_body_bytes()
        try:
            declared = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            declared = 0
        return bool(limit) and declared > limit

    def _redirect_for(self, payments):
        payments = [Payment.objects.get(pk=payment.pk) for payment in payments]
        first = payments[0]
        if first.batch_id:
            return self._redirect(status_value=first.status, batch_id=first.batch_id)
        return self._redirect(status_value=first.status, payment_id=first.pk)

    @staticmethod
    def _redirect(*, status_value, payment_id=None, batch_id=None):
        params = {}
        if batch_id:
            params["batch_id"] = str(batch_id)
        elif payment_id:
            params["payment_id"] = str(payment_id)
        params["status"] = status_value
        query = urlencode(params)

        target = conf.ui_redirect_url()
        if target:
            separator = "&" if "?" in target else "?"
            return HttpResponseRedirect(f"{target}{separator}{query}")
        body = (
            "<!doctype html><html><head><title>Payment</title></head>"
            f"<body><p>Payment status: {escape(status_value)}</p></body></html>"
        )
        return HttpResponse(body, content_type="text/html; charset=utf-8")
