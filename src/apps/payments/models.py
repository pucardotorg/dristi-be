"""Demands, their line items and the payments that settle them (spec 0017 #2).

The shape that matters is ``Payment -> PaymentDemandItem -> DemandItem``: a
payment is a collection transaction, and its ``PaymentDemandItem`` rows say
which items it pays. Paying one item, a subset or everything is the same code
path with a different list of items.

Balances (``paid_amount``, ``due_amount``) and statuses are written only by
``services/balances.py`` through ``PaymentService`` / ``DemandService``.
"""

from decimal import Decimal

from django.db import models
from django.db.models import F, Q

from apps.core.models import BaseAuditableModel, BaseModel

from .enums import (
    ChargeType,
    DemandItemStatus,
    DemandStatus,
    PaymentStatus,
    ReferenceType,
)
from .exceptions import ImmutableRecordError

MONEY = {"max_digits": 18, "decimal_places": 2}
ZERO = Decimal("0.00")


class UndeletableQuerySet(models.QuerySet):
    """Refuses bulk deletes, which bypass ``Model.delete()`` (spec 0017 #10)."""

    def delete(self):
        raise ImmutableRecordError(f"{self.model.__name__} rows are never deleted.")


class SnapshotMixin(models.Model):
    """Remember the values a row was loaded with, to guard frozen history."""

    snapshot_fields: tuple[str, ...] = ()

    class Meta:
        abstract = True

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded = {
            name: getattr(instance, name)
            for name in cls.snapshot_fields
            if name in instance.__dict__
        }
        return instance

    def loaded_value(self, name):
        """The value ``name`` had when this row was read, or ``None`` if new."""

        return getattr(self, "_loaded", {}).get(name)


class PaymentSequence(BaseModel):
    """A per-year counter behind ``DMD-`` and ``PAY-`` numbers (spec 0017 #11).

    Incremented with an ``UPDATE ... SET value = value + 1`` inside the
    creating transaction, so concurrent creation cannot hand out a number
    twice; the unique number columns are the backstop.
    """

    prefix = models.CharField(max_length=8)
    year = models.PositiveSmallIntegerField()
    value = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.UniqueConstraint(fields=["prefix", "year"], name="payments_sequence_unique"),
        ]

    def __str__(self):
        return f"{self.prefix}-{self.year}: {self.value}"


class Demand(BaseModel, BaseAuditableModel):
    """A raised, payable claim on a case: one or more charges grouped together."""

    Status = DemandStatus

    demand_number = models.CharField(max_length=32, unique=True)
    # TODO(cases): spec 0017 #2.1 makes this ``FK("cases.Case", on_delete=PROTECT,
    # related_name="demands")``. ``apps.cases`` is not on main yet, so the id is
    # kept as a plain UUID column with the same name (``case_id``) a ForeignKey
    # named ``case`` would use. Once the cases app merges, replace this field with
    # the FK. Write that migration by hand: ``makemigrations`` sees a removed
    # ``case_id`` and a new ``case`` and would drop the column with its data. Use
    # ``SeparateDatabaseAndState`` (state: remove ``case_id``, add ``case``;
    # database: keep the column, add the foreign-key constraint), after checking
    # every stored id exists in ``cases_case``.
    case_id = models.UUIDField(db_index=True)
    reference_type = models.CharField(max_length=32, choices=ReferenceType.choices)
    reference_id = models.CharField(max_length=64, db_index=True)
    organization_id = models.UUIDField(null=True, blank=True, db_index=True)
    # The party directed to pay. Informational: it does not limit who may pay.
    user_id = models.UUIDField(null=True, blank=True, db_index=True)
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(
        max_length=16, choices=DemandStatus.choices, default=DemandStatus.RAISED
    )
    total_amount = models.DecimalField(**MONEY, default=ZERO)
    paid_amount = models.DecimalField(**MONEY, default=ZERO)
    due_amount = models.DecimalField(**MONEY, default=ZERO)
    due_date = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.CheckConstraint(
                check=Q(total_amount__gte=0), name="payments_demand_total_non_negative"
            ),
            models.CheckConstraint(
                check=Q(paid_amount__gte=0), name="payments_demand_paid_non_negative"
            ),
            models.CheckConstraint(
                check=Q(due_amount__gte=0), name="payments_demand_due_non_negative"
            ),
            models.CheckConstraint(
                check=Q(paid_amount__lte=F("total_amount")),
                name="payments_demand_paid_within_total",
            ),
        ]
        indexes = [
            models.Index(fields=["case_id", "status"], name="payments_demand_case_status"),
            models.Index(
                fields=["reference_type", "reference_id"], name="payments_demand_reference"
            ),
            models.Index(fields=["user_id", "status"], name="payments_demand_user_status"),
        ]

    def __str__(self):
        return f"{self.demand_number} ({self.status})"

    @property
    def is_payable(self) -> bool:
        """Whether a new payment may be taken against this demand."""

        return self.status in (DemandStatus.RAISED, DemandStatus.PARTIALLY_PAID)


class DemandItem(SnapshotMixin, BaseModel, BaseAuditableModel):
    """One independently payable charge.

    ``description``, ``quantity``, ``unit_amount``, ``amount`` and
    ``account_head`` are a snapshot taken when the demand is raised; a later
    fee change cancels the item and raises a new one rather than editing it.
    """

    Status = DemandItemStatus
    snapshot_fields = ("status", "amount", "quantity", "unit_amount", "paid_amount")

    objects = UndeletableQuerySet.as_manager()

    demand = models.ForeignKey(Demand, on_delete=models.PROTECT, related_name="items")
    position = models.PositiveSmallIntegerField(default=0)
    charge_type = models.CharField(max_length=32, choices=ChargeType.choices)
    reference_type = models.CharField(max_length=32, choices=ReferenceType.choices)
    reference_id = models.CharField(max_length=64, db_index=True)
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"))
    unit_amount = models.DecimalField(**MONEY)
    amount = models.DecimalField(**MONEY)
    account_head = models.CharField(max_length=64, blank=True)
    paid_amount = models.DecimalField(**MONEY, default=ZERO)
    due_amount = models.DecimalField(**MONEY, default=ZERO)
    status = models.CharField(
        max_length=16, choices=DemandItemStatus.choices, default=DemandItemStatus.UNPAID
    )
    metadata = models.JSONField(default=dict, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        """Meta options."""

        ordering = ("demand_id", "position", "created_at")
        constraints = [
            models.CheckConstraint(check=Q(quantity__gt=0), name="payments_item_quantity_positive"),
            models.CheckConstraint(
                check=Q(unit_amount__gt=0), name="payments_item_unit_amount_positive"
            ),
            models.CheckConstraint(check=Q(amount__gt=0), name="payments_item_amount_positive"),
            models.CheckConstraint(
                check=Q(paid_amount__gte=0), name="payments_item_paid_non_negative"
            ),
            models.CheckConstraint(
                check=Q(due_amount__gte=0), name="payments_item_due_non_negative"
            ),
            models.CheckConstraint(
                check=Q(paid_amount__lte=F("amount")), name="payments_item_paid_within_amount"
            ),
        ]
        indexes = [
            models.Index(fields=["reference_type", "reference_id"], name="payments_item_reference"),
            models.Index(fields=["charge_type", "status"], name="payments_item_charge_status"),
        ]

    def __str__(self):
        return f"{self.description} — {self.amount} ({self.status})"

    def save(self, *args, **kwargs):
        """Refuse to change the money of an item that has been paid (spec 0017 #10)."""

        if not self._state.adding and self.loaded_value("status") == DemandItemStatus.PAID:
            frozen = ("amount", "quantity", "unit_amount", "paid_amount")
            changed = [name for name in frozen if getattr(self, name) != self.loaded_value(name)]
            if changed or self.status != DemandItemStatus.PAID:
                raise ImmutableRecordError(
                    "A paid demand item cannot be changed; raise a new demand instead."
                )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Items are cancelled, never deleted."""

        raise ImmutableRecordError("Demand items are cancelled, never deleted.")


class Payment(SnapshotMixin, BaseModel, BaseAuditableModel):
    """One collection attempt against one demand.

    The payments of a cross-demand checkout share a ``batch_id`` and one
    ``provider_payment_id`` and always move together. ``created_by`` is the
    user who made the payment.
    """

    Status = PaymentStatus
    snapshot_fields = ("status", "amount", "currency", "demand_id", "batch_id")

    objects = UndeletableQuerySet.as_manager()

    payment_number = models.CharField(max_length=32, unique=True)
    demand = models.ForeignKey(Demand, on_delete=models.PROTECT, related_name="payments")
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    amount = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.INITIATED
    )
    payment_mode = models.CharField(max_length=32, blank=True)
    provider = models.CharField(max_length=32, blank=True)
    provider_payment_id = models.CharField(max_length=128, blank=True)
    provider_reference = models.CharField(max_length=128, blank=True, db_index=True)
    client_request_id = models.CharField(max_length=128)
    payer = models.JSONField(default=dict, blank=True)
    needs_reconciliation = models.BooleanField(default=False, db_index=True)
    initiated_at = models.DateTimeField()
    completed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=64, blank=True)
    failure_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    poll_count = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name="payments_payment_amount_positive"),
            models.UniqueConstraint(
                fields=["demand", "client_request_id"],
                name="payments_payment_unique_client_request",
            ),
            # A provider id is unique only within its provider, and is shared
            # by the payments of one batch (one per demand).
            models.UniqueConstraint(
                fields=["provider", "provider_payment_id", "demand"],
                condition=~Q(provider="") & ~Q(provider_payment_id=""),
                name="payments_payment_unique_provider_id",
            ),
        ]
        indexes = [
            models.Index(
                fields=["provider", "provider_payment_id"], name="payments_payment_provider_id"
            ),
            models.Index(fields=["status", "last_polled_at"], name="payments_payment_poll"),
        ]
        # One permission per operator action: viewing payments must never be
        # enough to credit or resolve one (the admin is otherwise read-only).
        permissions = [
            ("confirm_payment_manually", "Can confirm a payment collected outside a provider"),
            ("resolve_payment_reconciliation", "Can mark a payment's reconciliation resolved"),
            ("recheck_payment_status", "Can re-check a payment's status with its provider"),
        ]

    def __str__(self):
        return f"{self.payment_number} ({self.status})"

    @property
    def is_open(self) -> bool:
        """Whether this payment may still collect money."""

        return self.status in (PaymentStatus.INITIATED, PaymentStatus.PENDING)

    def save(self, *args, **kwargs):
        """Freeze a successful payment's money and state (spec 0017 #10).

        Bookkeeping fields (``needs_reconciliation``, polling, metadata) stay
        writable so an operator can still resolve a flagged payment.
        """

        if not self._state.adding and self.loaded_value("status") == PaymentStatus.SUCCESS:
            frozen = ("status", "amount", "currency", "demand_id", "batch_id")
            if any(getattr(self, name) != self.loaded_value(name) for name in frozen):
                raise ImmutableRecordError("A successful payment cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Payment history is never deleted."""

        raise ImmutableRecordError("Payments are never deleted.")


class PaymentDemandItem(BaseModel, BaseAuditableModel):
    """Which demand item a payment pays, and for how much (always the full amount).

    Written once, when the payment is created; immutable thereafter.
    """

    objects = UndeletableQuerySet.as_manager()

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="items")
    demand_item = models.ForeignKey(
        DemandItem, on_delete=models.PROTECT, related_name="payment_items"
    )
    amount = models.DecimalField(**MONEY)

    class Meta:
        """Meta options."""

        ordering = ("payment_id", "created_at", "demand_item_id")
        constraints = [
            models.UniqueConstraint(
                fields=["payment", "demand_item"], name="payments_payment_item_unique"
            ),
            models.CheckConstraint(
                check=Q(amount__gt=0), name="payments_payment_item_amount_positive"
            ),
        ]

    def __str__(self):
        return f"{self.payment_id} -> {self.demand_item_id}: {self.amount}"

    def save(self, *args, **kwargs):
        """Rows are written once."""

        if not self._state.adding:
            raise ImmutableRecordError("Payment items cannot be changed once written.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Rows are never deleted."""

        raise ImmutableRecordError("Payment items are never deleted.")
