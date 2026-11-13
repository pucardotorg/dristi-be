"""Request and response serializers (spec 0017 #12).

Serializers check shape only: required fields, formats, enum values, a
non-empty duplicate-free item list. Case access, payability and balances are
decided in the services under a row lock (#6.3), which a serializer cannot
hold. Amounts are strings on the wire, never JSON numbers (#16).
"""

from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.api.serializers import AuditedModelSerializer

from . import conf, errors
from .enums import AttestationOutcome, PaymentStatus
from .models import Demand, DemandItem, Payment, PaymentAttestation, PaymentDemandItem


def duplicate_free(values, error):
    """Raise ``error`` on the first repeated value, on that value's index."""

    seen = set()
    for index, value in enumerate(values):
        if value in seen:
            raise error.validation_error({index: [error.message]})
        seen.add(value)
    return values


# ---------------------------------------------------------------------------
# Demands
# ---------------------------------------------------------------------------
class DemandItemSerializer(serializers.ModelSerializer):
    """A line item as returned to the payer."""

    class Meta:
        """Meta options."""

        model = DemandItem
        fields = (
            "id",
            "position",
            "charge_type",
            "reference_type",
            "reference_id",
            "description",
            "quantity",
            "unit_amount",
            "amount",
            "account_head",
            "paid_amount",
            "due_amount",
            "status",
            "metadata",
            "cancelled_at",
            "cancellation_reason",
        )
        read_only_fields = fields


class PaymentSummarySerializer(serializers.Serializer):
    """How many collection attempts a demand has had, by outcome."""

    count = serializers.IntegerField()
    successful = serializers.IntegerField()
    in_flight = serializers.IntegerField()
    failed = serializers.IntegerField()
    cancelled = serializers.IntegerField()


class DemandSerializer(AuditedModelSerializer):
    """A demand with its items and a payment summary."""

    case_id = serializers.UUIDField(read_only=True)
    items = DemandItemSerializer(many=True, read_only=True)
    payment_summary = serializers.SerializerMethodField()

    class Meta:
        """Meta options."""

        model = Demand
        fields = (
            "id",
            "demand_number",
            "case_id",
            "reference_type",
            "reference_id",
            "organization_id",
            "user_id",
            "currency",
            "status",
            "total_amount",
            "paid_amount",
            "due_amount",
            "due_date",
            "metadata",
            "cancelled_at",
            "cancellation_reason",
            "items",
            "payment_summary",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        )
        read_only_fields = fields

    @extend_schema_field(PaymentSummarySerializer)
    def get_payment_summary(self, demand) -> dict:
        """Count the demand's payments by outcome (uses the prefetched rows)."""

        statuses = [payment.status for payment in demand.payments.all()]
        return {
            "count": len(statuses),
            "successful": statuses.count(PaymentStatus.SUCCESS),
            "in_flight": sum(
                1
                for status in statuses
                if status in (PaymentStatus.INITIATED, PaymentStatus.PENDING)
            ),
            "failed": statuses.count(PaymentStatus.FAILED),
            "cancelled": statuses.count(PaymentStatus.CANCELLED),
        }


class CancelSerializer(serializers.Serializer):
    """Body of the cancel endpoints."""

    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class PayerSerializer(serializers.Serializer):
    """Payer details sent to the provider; missing fields come from the caller's profile."""

    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    email = serializers.CharField(max_length=254, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=128, required=False, allow_blank=True)
    pincode = serializers.CharField(max_length=12, required=False, allow_blank=True)


class ItemIdsField(serializers.ListField):
    """A non-empty list of demand item ids."""

    child = serializers.UUIDField()

    def __init__(self, **kwargs):
        kwargs.setdefault("allow_empty", False)
        super().__init__(**kwargs)


class PaymentCreateSerializer(serializers.Serializer):
    """Body of ``POST /payments/demands/{id}/payments/``.

    ``client_request_id`` may come from the ``Idempotency-Key`` header instead.
    Item amounts are never accepted: each item is paid in full.
    """

    client_request_id = serializers.CharField(max_length=128)
    payment_mode = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    demand_item_ids = ItemIdsField()
    payer = PayerSerializer(required=False)
    provider = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        default="",
        help_text="One of GET /payments/providers/; empty uses the default (spec 0032 #4.2).",
    )
    provider_options = serializers.DictField(
        child=serializers.CharField(max_length=255, allow_blank=True), required=False, default=dict
    )

    def validate_demand_item_ids(self, value):
        """No item twice in one request (spec 0017 #6.3 rule 1)."""

        return duplicate_free(value, errors.DUPLICATE_DEMAND_ITEM)


class BatchSelectionSerializer(serializers.Serializer):
    """The items of one demand within a batch."""

    demand_id = serializers.UUIDField()
    demand_item_ids = ItemIdsField()

    def validate_demand_item_ids(self, value):
        """No item twice in one selection."""

        return duplicate_free(value, errors.DUPLICATE_DEMAND_ITEM)


class BatchCreateSerializer(serializers.Serializer):
    """Body of ``POST /payments/batches/``."""

    client_request_id = serializers.CharField(max_length=128)
    payment_mode = serializers.CharField(
        max_length=32, required=False, allow_blank=True, default=""
    )
    selections = BatchSelectionSerializer(many=True, allow_empty=False)
    payer = PayerSerializer(required=False)
    provider = serializers.CharField(
        max_length=32,
        required=False,
        allow_blank=True,
        default="",
        help_text="One of GET /payments/providers/; empty uses the default (spec 0032 #4.2).",
    )
    provider_options = serializers.DictField(
        child=serializers.CharField(max_length=255, allow_blank=True), required=False, default=dict
    )

    def validate_selections(self, value):
        """Cap the batch and refuse a demand listed twice (spec 0017 #12.3)."""

        if len(value) > conf.batch_max_demands():
            raise errors.BATCH_TOO_LARGE.validation_error()
        seen = set()
        for index, selection in enumerate(value):
            if selection["demand_id"] in seen:
                raise errors.DEMAND_REPEATED_IN_BATCH.validation_error(
                    {index: {"demand_id": [errors.DEMAND_REPEATED_IN_BATCH.message]}}
                )
            seen.add(selection["demand_id"])
        return value


class PaymentItemSerializer(serializers.ModelSerializer):
    """A demand item a payment pays, and for how much."""

    demand_item_id = serializers.UUIDField(read_only=True)
    charge_type = serializers.CharField(source="demand_item.charge_type", read_only=True)
    description = serializers.CharField(source="demand_item.description", read_only=True)
    reference_type = serializers.CharField(source="demand_item.reference_type", read_only=True)
    reference_id = serializers.CharField(source="demand_item.reference_id", read_only=True)

    class Meta:
        """Meta options."""

        model = PaymentDemandItem
        fields = (
            "demand_item_id",
            "amount",
            "charge_type",
            "description",
            "reference_type",
            "reference_id",
        )
        read_only_fields = fields


class PayerAttestationSerializer(serializers.Serializer):
    """What the payer sees of a recorded collection; never who recorded it."""

    receipt_number = serializers.CharField()
    method = serializers.CharField()
    collected_at = serializers.DateTimeField()


class PaymentSerializer(AuditedModelSerializer):
    """A payment with the demand items it pays. ``created_by`` is the payer."""

    demand_id = serializers.UUIDField(read_only=True)
    demand_number = serializers.CharField(source="demand.demand_number", read_only=True)
    items = PaymentItemSerializer(many=True, read_only=True)
    attestation = serializers.SerializerMethodField()

    class Meta:
        """Meta options."""

        model = Payment
        fields = (
            "id",
            "payment_number",
            "demand_id",
            "demand_number",
            "batch_id",
            "amount",
            "currency",
            "status",
            "payment_mode",
            "provider",
            "provider_payment_id",
            "provider_reference",
            "needs_reconciliation",
            "initiated_at",
            "completed_at",
            "failed_at",
            "cancelled_at",
            "failure_code",
            "failure_message",
            "items",
            "attestation",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        )
        read_only_fields = fields

    @extend_schema_field(PayerAttestationSerializer(allow_null=True))
    def get_attestation(self, payment) -> dict | None:
        """The recorded collection of an attested payment (spec 0032 #4.8).

        Read from ``context["attestations"]`` when the view prefetched them,
        else looked up by the payment's provider transaction.
        """

        if not (payment.provider and payment.provider_payment_id):
            return None
        key = (payment.provider, payment.provider_payment_id)
        prefetched = self.context.get("attestations")
        if prefetched is not None:
            attestation = prefetched.get(key)
        else:
            attestation = PaymentAttestation.objects.filter(
                provider=payment.provider, provider_payment_id=payment.provider_payment_id
            ).first()
        if attestation is None:
            return None
        return PayerAttestationSerializer(attestation).data


class ActionDetailSerializer(serializers.Serializer):
    """One label/value line of a ``SHOW_INSTRUCTIONS`` action."""

    key = serializers.CharField()
    label = serializers.CharField()
    value = serializers.CharField()


class ProviderActionSerializer(serializers.Serializer):
    """What the client renders, uninterpreted.

    ``REDIRECT_FORM``: post ``form_fields`` to ``url``. ``SHOW_INSTRUCTIONS``:
    show ``details`` in order (spec 0032 #4.1).
    """

    kind = serializers.CharField()
    url = serializers.CharField(allow_blank=True)
    method = serializers.CharField(allow_blank=True)
    form_fields = serializers.DictField(child=serializers.CharField())
    details = ActionDetailSerializer(many=True)


def action_payload(action) -> dict | None:
    """Shape a ``ProviderAction`` for the response."""

    if action is None:
        return None
    return {
        "kind": str(action.kind),
        "url": action.url,
        "method": action.method,
        "form_fields": dict(action.form_fields),
        "details": [
            {"key": detail.key, "label": detail.label, "value": detail.value}
            for detail in action.details
        ],
    }


class PaymentCreatedSerializer(PaymentSerializer):
    """A new (or replayed) payment, with the provider action when there is one."""

    provider_action = serializers.SerializerMethodField()

    class Meta(PaymentSerializer.Meta):
        """Meta options."""

        fields = (*PaymentSerializer.Meta.fields, "provider_action")
        read_only_fields = fields

    @extend_schema_field(ProviderActionSerializer(allow_null=True))
    def get_provider_action(self, payment) -> dict | None:
        """The action passed in the serializer context."""

        return action_payload(self.context.get("provider_action"))


class BatchSerializer(serializers.Serializer):
    """The payments of one cross-demand checkout."""

    batch_id = serializers.UUIDField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField()
    status = serializers.ChoiceField(choices=PaymentStatus.choices)
    provider_action = ProviderActionSerializer(allow_null=True, required=False)
    payments = PaymentSerializer(many=True)


def batch_payload(payments, action=None) -> dict:
    """Shape a batch (its payments always share one status)."""

    first = payments[0]
    return {
        "batch_id": first.batch_id,
        "amount": sum((payment.amount for payment in payments), Decimal("0.00")),
        "currency": first.currency,
        "status": first.status,
        "provider_action": action_payload(action),
        "payments": payments,
    }


class PaymentOptionSerializer(serializers.Serializer):
    """One choice offered by the provider."""

    code = serializers.CharField()
    label = serializers.CharField()
    group = serializers.CharField()


class ProviderOptionsSerializer(serializers.Serializer):
    """The default provider's options (spec 0017 #12.4)."""

    provider = serializers.CharField(allow_blank=True)
    options = PaymentOptionSerializer(many=True)


class SelectableProviderSerializer(serializers.Serializer):
    """One provider a payer may choose (spec 0032 #9.1.1)."""

    name = serializers.CharField()
    label = serializers.CharField()
    confirmation = serializers.CharField()
    options = PaymentOptionSerializer(many=True)


class ProviderListSerializer(serializers.Serializer):
    """Every provider a payer may choose, in order, and the default."""

    default = serializers.CharField(allow_blank=True)
    providers = SelectableProviderSerializer(many=True)


class PaymentActionSerializer(serializers.Serializer):
    """The rebuilt provider action of a pending payment (spec 0032 #4.8)."""

    payment_id = serializers.UUIDField()
    provider = serializers.CharField()
    provider_payment_id = serializers.CharField()
    provider_action = ProviderActionSerializer()


# ---------------------------------------------------------------------------
# Collection desk (spec 0032 #9.2, #9.3)
# ---------------------------------------------------------------------------
def mask_phone(phone: str) -> str:
    """``******3210``: staff recognise the payer, they do not contact them."""

    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if not digits:
        return ""
    return "*" * 6 + digits[-4:]


class StrictDecimalField(serializers.DecimalField):
    """A positive money amount sent as a string or number, at most two decimals."""

    def __init__(self, **kwargs):
        kwargs.setdefault("max_digits", 18)
        kwargs.setdefault("decimal_places", 2)
        kwargs.setdefault("min_value", Decimal("0.01"))
        super().__init__(**kwargs)


class FlatStringMapField(serializers.DictField):
    """A flat ``{str: str}`` map: nested objects and lists are refused."""

    child = serializers.CharField(max_length=255, allow_blank=True)

    def to_internal_value(self, data):
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict | list | bool) or value is None:
                    raise serializers.ValidationError(
                        {key: ["Must be a string."]}, code="incorrect_type"
                    )
        return super().to_internal_value(data)


class AwareDateTimeField(serializers.DateTimeField):
    """An ISO-8601 datetime that must carry its UTC offset."""

    default_error_messages = {"naive": "Include a UTC offset, e.g. +05:30."}

    def to_internal_value(self, value):
        parsed = super().to_internal_value(value)
        text = str(value)
        if "T" not in text or not (text.endswith("Z") or "+" in text[10:] or "-" in text[10:]):
            self.fail("naive")
        return parsed


class CollectionConfirmSerializer(serializers.Serializer):
    """Body of ``POST /collections/{provider}/{reference}/confirm/`` (spec 0032 #9.2.2).

    Shape only: business rules come from the service and the provider.
    """

    amount = StrictDecimalField()
    method = serializers.CharField(max_length=32)
    receipt_number = serializers.CharField(max_length=64)
    collected_at = AwareDateTimeField(required=False, allow_null=True, default=None)
    details = FlatStringMapField(required=False, default=dict)
    remarks = serializers.CharField(required=False, allow_blank=True, default="")
    late = serializers.BooleanField(required=False, default=False)


class CollectionCancelSerializer(serializers.Serializer):
    """Body of ``POST /collections/{provider}/{reference}/cancel/`` (spec 0032 #9.2.3)."""

    reason = serializers.CharField(max_length=255)


class CollectionPayerSerializer(serializers.Serializer):
    """The payer as staff see them: name and a masked phone."""

    name = serializers.CharField(allow_blank=True)
    phone = serializers.CharField(allow_blank=True)


class CollectionCaseSerializer(serializers.Serializer):
    """The case a payment's demand is raised on.

    ``display_number`` is the case number once registered, else the filing
    number, as the cases selector reports it.
    """

    id = serializers.UUIDField()
    display_number = serializers.CharField(allow_blank=True)


class CollectionItemSerializer(serializers.Serializer):
    """One demand item a collection pays."""

    demand_item_id = serializers.UUIDField()
    charge_type = serializers.CharField()
    description = serializers.CharField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class CollectionPaymentSerializer(serializers.Serializer):
    """One payment of a collection request."""

    id = serializers.UUIDField()
    payment_number = serializers.CharField()
    demand_number = serializers.CharField()
    case = CollectionCaseSerializer()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    status = serializers.ChoiceField(choices=PaymentStatus.choices)
    items = CollectionItemSerializer(many=True, required=False)


class RecorderSerializer(serializers.Serializer):
    """Who recorded a collection."""

    id = serializers.UUIDField(allow_null=True)
    name = serializers.CharField(allow_blank=True)


class AttestationSerializer(serializers.ModelSerializer):
    """A recorded collection as staff see it."""

    recorded_by = serializers.SerializerMethodField()
    recorded_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        """Meta options."""

        model = PaymentAttestation
        fields = (
            "receipt_number",
            "method",
            "amount",
            "collected_at",
            "details",
            "remarks",
            "outcome",
            "recorded_by",
            "recorded_at",
        )
        read_only_fields = fields

    @extend_schema_field(RecorderSerializer)
    def get_recorded_by(self, attestation) -> dict:
        """The recorder's id and name."""

        user = attestation.created_by
        return {
            "id": getattr(user, "pk", None),
            "name": (getattr(user, "name", "") or "") if user else "",
        }


class CollectionSerializer(serializers.Serializer):
    """One attested payment request: what is due, for what, and its record (#9.2.1)."""

    provider = serializers.CharField()
    reference = serializers.CharField()
    status = serializers.ChoiceField(choices=PaymentStatus.choices)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField()
    initiated_at = serializers.DateTimeField()
    valid_until = serializers.DateTimeField(allow_null=True)
    expired = serializers.BooleanField()
    batch_id = serializers.UUIDField(allow_null=True)
    payer = CollectionPayerSerializer()
    payments = CollectionPaymentSerializer(many=True)
    attestation = AttestationSerializer(allow_null=True)


class MethodFieldSerializer(serializers.Serializer):
    """One input of a collection method."""

    key = serializers.CharField()
    label = serializers.CharField()
    kind = serializers.CharField()
    required = serializers.BooleanField()
    max_length = serializers.IntegerField()


class CollectionMethodSerializer(serializers.Serializer):
    """A way money can be handed over, and the fields to record it."""

    code = serializers.CharField()
    label = serializers.CharField()
    fields = MethodFieldSerializer(many=True)


class CollectionMethodsSerializer(serializers.Serializer):
    """The collection methods of one attested provider."""

    provider = serializers.CharField()
    methods = CollectionMethodSerializer(many=True)


class RegisterEntrySerializer(serializers.ModelSerializer):
    """One row of the collection register (spec 0032 #9.3)."""

    reference = serializers.CharField(source="provider_payment_id", read_only=True)
    payment_numbers = serializers.SerializerMethodField()
    recorded_by = serializers.SerializerMethodField()
    recorded_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        """Meta options."""

        model = PaymentAttestation
        fields = (
            "id",
            "provider",
            "reference",
            "payment_numbers",
            "amount",
            "currency",
            "method",
            "receipt_number",
            "collected_at",
            "recorded_by",
            "recorded_at",
            "outcome",
        )
        read_only_fields = fields

    def get_payment_numbers(self, attestation) -> list[str]:
        """Payment numbers of the request, from ``context["payment_numbers"]``."""

        numbers = self.context.get("payment_numbers") or {}
        return numbers.get((attestation.provider, attestation.provider_payment_id), [])

    @extend_schema_field(RecorderSerializer)
    def get_recorded_by(self, attestation) -> dict:
        """The recorder's id and name."""

        return AttestationSerializer.get_recorded_by(self, attestation)


class RegisterTotalSerializer(serializers.Serializer):
    """Count and sum of the register's rows for one method."""

    method = serializers.CharField()
    count = serializers.IntegerField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)


class CollectionListFilterSerializer(serializers.Serializer):
    """Query parameters of the collection list (spec 0032 #9.2.4)."""

    provider = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=PaymentStatus.choices, required=False)
    search = serializers.CharField(required=False, allow_blank=True, max_length=128)
    initiated_from = serializers.DateField(required=False)
    initiated_to = serializers.DateField(required=False)


class RegisterFilterSerializer(serializers.Serializer):
    """Query parameters of the collection register (spec 0032 #9.3)."""

    provider = serializers.CharField(required=False, allow_blank=True)
    collected_on = serializers.DateField(required=False)
    recorded_by = serializers.UUIDField(required=False)
    method = serializers.CharField(required=False, allow_blank=True, max_length=32)
    outcome = serializers.ChoiceField(choices=AttestationOutcome.choices, required=False)


class MethodsFilterSerializer(serializers.Serializer):
    """Query parameters of the methods endpoint."""

    provider = serializers.CharField(max_length=32)


class RegisterPageSerializer(serializers.Serializer):
    """A page of the collection register, with totals per method for the filter."""

    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = RegisterEntrySerializer(many=True)
    totals = RegisterTotalSerializer(many=True)
