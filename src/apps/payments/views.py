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
from django.utils import timezone
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
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, BasePermission
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle
from rest_framework.views import APIView

from apps.api import errors as api_errors
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
    CollectionCancelSerializer,
    CollectionConfirmSerializer,
    CollectionListFilterSerializer,
    CollectionMethodsSerializer,
    CollectionSerializer,
    DemandSerializer,
    MethodsFilterSerializer,
    PaymentActionSerializer,
    PaymentCreatedSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    ProviderListSerializer,
    ProviderOptionsSerializer,
    RegisterEntrySerializer,
    RegisterFilterSerializer,
    RegisterPageSerializer,
    RegisterTotalSerializer,
    action_payload,
    batch_payload,
    mask_phone,
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
    errors.PROVIDER_NOT_AVAILABLE.example(field="provider"),
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
        context = {"attestations": selectors.attestations_for(page)}
        return self.get_paginated_response(PaymentSerializer(page, many=True, context=context).data)

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
            provider=data.get("provider", ""),
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
    provider_action=extend_schema(
        responses=error_responses(
            errors.NOT_PAYMENT_CREATOR,
            errors.COLLECTION_NOT_OPEN,
            errors.PROVIDER_REJECTED,
            errors.PROVIDER_UNAVAILABLE,
            errors.PROVIDER_REPLAY_MISMATCH,
        ),
    ),
)
class PaymentViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Retrieve a payment (the client's source of truth), cancel it, re-show its action."""

    serializer_class = PaymentSerializer
    lookup_url_kwarg = "payment_id"
    lookup_value_regex = UUID_REGEX

    def get_queryset(self):
        """Payments the caller may see."""

        return selectors.payments_for(self.request.user)

    def get_serializer_class(self):
        """Pick the serializer for the action."""

        if self.action == "cancel":
            return CancelSerializer
        if self.action == "provider_action":
            return PaymentActionSerializer
        return PaymentSerializer

    @action(detail=True, methods=["get"], url_path="action", url_name="action")
    def provider_action(self, request, *args, **kwargs):
        """The instructions (or form) of a pending payment, rebuilt (spec 0032 #4.8)."""

        payment = self.get_object()
        provider_action = PaymentService.pending_action(payment, actor=request.user)
        return Response(
            PaymentActionSerializer(
                {
                    "payment_id": payment.pk,
                    "provider": payment.provider,
                    "provider_payment_id": payment.provider_payment_id,
                    "provider_action": action_payload(provider_action),
                }
            ).data
        )

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
            provider=data.get("provider", ""),
            actor=request.user,
        )
        payments = selectors.batch_payments(request.user, collection.batch_id)
        context = {"attestations": selectors.attestations_for(payments)}
        return Response(
            BatchSerializer(batch_payload(payments, collection.action), context=context).data,
            status=status.HTTP_201_CREATED if collection.created else status.HTTP_200_OK,
        )

    def retrieve(self, request, *args, batch_id=None, **kwargs):
        """The payments of one batch."""

        payments = selectors.batch_payments(request.user, batch_id)
        if not payments:
            raise NotFound()
        context = {"attestations": selectors.attestations_for(payments)}
        return Response(BatchSerializer(batch_payload(payments), context=context).data)


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


class ProviderListView(APIView):
    """``GET /payments/providers/`` — every provider a payer may choose (spec 0032 #9.1.1)."""

    @extend_schema(
        operation_id="payments_providers",
        responses={200: ProviderListSerializer, **error_responses(errors.PROVIDER_UNAVAILABLE)},
    )
    def get(self, request):
        """Providers in ``PAYMENT_SELECTABLE_PROVIDERS`` order, with their options."""

        default = conf.default_provider()
        providers = []
        for name in registry.selectable_names():
            try:
                provider = registry.get(name)
                options = _cached_options(provider)
            except (ProviderError, ProviderNotConfigured) as exc:
                if name == default:
                    raise BusinessError(errors.PROVIDER_UNAVAILABLE) from exc
                logger.warning("Payment provider %s left out of the provider list: %s", name, exc)
                continue
            providers.append(
                {
                    "name": provider.name,
                    "label": provider.label or provider.name,
                    "confirmation": str(provider.confirmation),
                    "options": options,
                }
            )
        return Response(ProviderListSerializer({"default": default, "providers": providers}).data)


def _cached_options(provider) -> list[dict]:
    """A provider's options, cached for five minutes (spec 0017 #12.4)."""

    key = f"payments:provider-options:{provider.name}"
    options = cache.get(key)
    if options is None:
        options = [
            {"code": option.code, "label": option.label, "group": option.group}
            for option in provider.list_options()
        ]
        cache.set(key, options, OPTIONS_CACHE_SECONDS)
    return options


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


# ---------------------------------------------------------------------------
# Collection desk (spec 0032 #9.2, #9.3)
# ---------------------------------------------------------------------------
class HasPaymentPermission(BasePermission):
    """The caller holds ``payments.<codename>`` (spec 0032 #4.7).

    Used as an instance in ``permission_classes``: DRF calls each entry, and an
    instance returns itself.
    """

    message = api_errors.PERMISSION_DENIED.message
    code = api_errors.PERMISSION_DENIED.code

    def __init__(self, codename: str):
        self.codename = codename

    def __call__(self):
        return self

    def has_permission(self, request, view):
        """Whether the signed-in caller holds the permission."""

        user = request.user
        return bool(user and user.is_authenticated and user.has_perm(f"payments.{self.codename}"))


def staff_permissions(codename: str) -> list:
    """The default gates plus one payments permission; never case-scoped."""

    return [*api_settings.DEFAULT_PERMISSION_CLASSES, HasPaymentPermission(codename)]


class FailedLookupThrottle(SimpleRateThrottle):
    """Per-user limit on failed collection lookups (spec 0032 #15).

    Only a lookup that finds nothing, or names a malformed reference, counts,
    so a busy counter is never slowed down while the reference space cannot be
    enumerated even by an authorised account.
    """

    scope = "payments_collection_lookup"

    def get_rate(self):
        """The configured rate, or ``None`` to disable throttling."""

        return conf.collection_lookup_throttle_rate() or None

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}

    def allow_request(self, request, view):
        """Refuse once the caller's failures in the window reach the rate; record nothing."""

        if self.rate is None:
            return True
        self.key = self.get_cache_key(request, view)
        self.history = self.cache.get(self.key, [])
        self.now = self.timer()
        while self.history and self.history[-1] <= self.now - self.duration:
            self.history.pop()
        if len(self.history) >= self.num_requests:
            return self.throttle_failure()
        return True

    def record_failure(self, request, view) -> None:
        """Count one failed lookup."""

        if self.rate is None:
            return
        key = self.get_cache_key(request, view)
        now = self.timer()
        history = [moment for moment in self.cache.get(key, []) if moment > now - self.duration]
        self.cache.set(key, [now, *history], self.duration)


def resolve_reference(provider_name: str, reference: str) -> str:
    """The canonical reference of an attested provider (spec 0032 #9.2).

    An unknown or non-attested provider is ``404 E00105``; a reference that is
    not one of the provider's (a failed check symbol) is ``400 E00001``.
    """

    provider = PaymentService.attested_provider(provider_name)
    try:
        return provider.normalise_reference(reference)
    except ProviderError:
        raise BusinessError(
            api_errors.INVALID, "This is not a valid payment reference.", field="reference"
        ) from None


def collection_payload(request_obj: selectors.CollectionRequest, *, items: bool = True) -> dict:
    """Shape a collection request for ``CollectionSerializer``."""

    first = request_obj.first
    valid_until = request_obj.valid_until
    payments = []
    for payment in request_obj.payments:
        summary = request_obj.cases.get(payment.demand.case_id)
        row = {
            "id": payment.pk,
            "payment_number": payment.payment_number,
            "demand_number": payment.demand.demand_number,
            "case": {
                "id": payment.demand.case_id,
                "display_number": summary.display_number if summary else "",
            },
            "amount": payment.amount,
            "status": payment.status,
        }
        if items:
            row["items"] = [
                {
                    "demand_item_id": line.demand_item_id,
                    "charge_type": line.demand_item.charge_type,
                    "description": line.demand_item.description,
                    "amount": line.amount,
                }
                for line in payment.items.all()
            ]
        payments.append(row)
    return {
        "provider": request_obj.provider,
        "reference": request_obj.reference,
        "status": first.status,
        "amount": request_obj.amount,
        "currency": first.currency,
        "initiated_at": request_obj.initiated_at,
        "valid_until": valid_until,
        "expired": bool(valid_until and timezone.now() > valid_until),
        "batch_id": first.batch_id,
        "payer": {
            "name": str(first.payer.get("name") or ""),
            "phone": mask_phone(first.payer.get("phone")),
        },
        "payments": payments,
        "attestation": request_obj.attestation,
    }


def collection_response(provider: str, reference: str) -> Response:
    request_obj = selectors.collection_request(provider, reference)
    if request_obj is None:
        raise BusinessError(api_errors.NOT_FOUND)
    return Response(CollectionSerializer(collection_payload(request_obj)).data)


COLLECTION_PATH_PARAMETERS = [
    OpenApiParameter(
        "provider", OpenApiTypes.STR, OpenApiParameter.PATH, description="An ATTESTED provider."
    ),
    OpenApiParameter(
        "reference",
        OpenApiTypes.STR,
        OpenApiParameter.PATH,
        description="The payment request reference, in any case, with or without dashes.",
    ),
]
REFERENCE_INVALID = api_errors.INVALID.example(
    "This is not a valid payment reference.", field="reference"
)


class CollectionMethodsView(APIView):
    """``GET /payments/collections/methods/?provider=`` — what a staff form renders."""

    def get_permissions(self):
        return [permission() for permission in staff_permissions("view_payment_collection")]

    @extend_schema(
        operation_id="payments_collection_methods",
        parameters=[MethodsFilterSerializer],
        responses={200: CollectionMethodsSerializer, **error_responses(api_errors.NOT_FOUND)},
    )
    def get(self, request):
        """The collection methods of an attested provider, with their fields."""

        filters = MethodsFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        provider = PaymentService.attested_provider(filters.validated_data["provider"])
        methods = [
            {
                "code": method.code,
                "label": method.label,
                "fields": [
                    {
                        "key": field.key,
                        "label": field.label,
                        "kind": field.kind,
                        "required": field.required,
                        "max_length": field.max_length,
                    }
                    for field in method.fields
                ],
            }
            for method in provider.attestation_methods()
        ]
        return Response(
            CollectionMethodsSerializer({"provider": provider.name, "methods": methods}).data
        )


class CollectionListView(GenericAPIView):
    """``GET /payments/collections/`` — attested requests, one row per request."""

    serializer_class = CollectionSerializer

    def get_permissions(self):
        return [permission() for permission in staff_permissions("view_payment_collection")]

    @extend_schema(
        operation_id="payments_collections_list",
        parameters=[CollectionListFilterSerializer],
        responses=CollectionSerializer(many=True),
    )
    def get(self, request):
        """Newest first; ``search`` matches reference, payment, demand or case number, payer."""

        filters = CollectionListFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        rows = selectors.collection_requests(**filters.validated_data)
        page = self.paginate_queryset(rows)
        payloads = [
            collection_payload(request_obj, items=False)
            for request_obj in selectors.collection_requests_page(page)
        ]
        return self.get_paginated_response(CollectionSerializer(payloads, many=True).data)


class CollectionRegisterView(GenericAPIView):
    """``GET /payments/collections/register/`` — recorded collections, for the day-end tally."""

    serializer_class = RegisterEntrySerializer

    def get_permissions(self):
        return [permission() for permission in staff_permissions("view_payment_collection")]

    @extend_schema(
        operation_id="payments_collection_register",
        parameters=[RegisterFilterSerializer],
        responses={200: RegisterPageSerializer},
    )
    def get(self, request):
        """Read-only; ``collected_on`` is an IST date. Not a cash book."""

        filters = RegisterFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        rows = selectors.collection_register(**filters.validated_data)
        page = self.paginate_queryset(rows)
        data = RegisterEntrySerializer(
            page,
            many=True,
            context={"payment_numbers": selectors.register_payment_numbers(page)},
        ).data
        response = self.get_paginated_response(data)
        response.data["totals"] = RegisterTotalSerializer(
            selectors.register_totals(rows), many=True
        ).data
        return response


class CollectionDetailView(APIView):
    """``GET /payments/collections/{provider}/{reference}/`` — one request, for the clerk."""

    def get_permissions(self):
        return [permission() for permission in staff_permissions("view_payment_collection")]

    def get_throttles(self):
        return [*super().get_throttles(), FailedLookupThrottle()]

    @extend_schema(
        operation_id="payments_collection_retrieve",
        parameters=COLLECTION_PATH_PARAMETERS,
        responses={200: CollectionSerializer, **error_responses(REFERENCE_INVALID)},
    )
    def get(self, request, provider, reference):
        """Amount due, items, case, masked payer, validity and any recorded collection."""

        try:
            canonical = resolve_reference(provider, reference)
            return collection_response(provider, canonical)
        except BusinessError as exc:
            if exc.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND):
                FailedLookupThrottle().record_failure(request, self)
            raise


class CollectionConfirmView(APIView):
    """``POST /payments/collections/{provider}/{reference}/confirm/`` — record the money."""

    def get_permissions(self):
        return [permission() for permission in staff_permissions("record_payment_collection")]

    @extend_schema(
        operation_id="payments_collection_confirm",
        parameters=COLLECTION_PATH_PARAMETERS,
        request=CollectionConfirmSerializer,
        responses={
            200: CollectionSerializer,
            **error_responses(
                REFERENCE_INVALID,
                errors.COLLECTION_DETAILS_INVALID.example(field="amount"),
                errors.COLLECTION_DETAILS_INVALID.example(field="details.instrument_number"),
                errors.COLLECTOR_IS_PAYER,
                errors.COLLECTION_NOT_OPEN,
                errors.RECEIPT_NUMBER_USED.example(field="receipt_number"),
                errors.COLLECTION_REJECTED,
                errors.PROVIDER_UNAVAILABLE,
                api_errors.NOT_FOUND,
                api_errors.CONFLICT,
            ),
        },
    )
    def post(self, request, provider, reference):
        """Record that the exact amount due was received; ``200`` on an identical replay."""

        canonical = resolve_reference(provider, reference)
        serializer = CollectionConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["late"] and not request.user.has_perm("payments.record_late_payment_collection"):
            raise BusinessError(api_errors.PERMISSION_DENIED)
        PaymentService.record_collection(
            provider=provider,
            provider_payment_id=canonical,
            amount=data["amount"],
            method=data["method"],
            receipt_number=data["receipt_number"],
            collected_at=data["collected_at"],
            details=data["details"],
            remarks=data["remarks"],
            late=data["late"],
            actor=request.user,
        )
        return collection_response(provider, canonical)


class CollectionCancelView(APIView):
    """``POST /payments/collections/{provider}/{reference}/cancel/`` — on the payer's behalf."""

    def get_permissions(self):
        return [permission() for permission in staff_permissions("cancel_payment_collection")]

    @extend_schema(
        operation_id="payments_collection_cancel",
        parameters=COLLECTION_PATH_PARAMETERS,
        request=CollectionCancelSerializer,
        responses={
            200: CollectionSerializer,
            **error_responses(
                REFERENCE_INVALID, errors.PAYMENT_NOT_CANCELLABLE, api_errors.NOT_FOUND
            ),
        },
    )
    def post(self, request, provider, reference):
        """Cancel an open request with a reason; its items become payable again."""

        canonical = resolve_reference(provider, reference)
        serializer = CollectionCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        PaymentService.cancel_collection(
            provider=provider,
            provider_payment_id=canonical,
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return collection_response(provider, canonical)
