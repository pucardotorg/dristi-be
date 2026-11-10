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
from .enums import PaymentStatus
from .models import Demand, DemandItem, Payment, PaymentDemandItem


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


class PaymentSerializer(AuditedModelSerializer):
    """A payment with the demand items it pays. ``created_by`` is the payer."""

    demand_id = serializers.UUIDField(read_only=True)
    demand_number = serializers.CharField(source="demand.demand_number", read_only=True)
    items = PaymentItemSerializer(many=True, read_only=True)

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
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
        )
        read_only_fields = fields


class ProviderActionSerializer(serializers.Serializer):
    """What the client renders, uninterpreted: post ``form_fields`` to ``url``."""

    kind = serializers.CharField()
    url = serializers.CharField(allow_blank=True)
    method = serializers.CharField()
    form_fields = serializers.DictField(child=serializers.CharField())


def action_payload(action) -> dict | None:
    """Shape a ``ProviderAction`` for the response."""

    if action is None:
        return None
    return {
        "kind": str(action.kind),
        "url": action.url,
        "method": action.method,
        "form_fields": dict(action.form_fields),
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
