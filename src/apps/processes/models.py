"""Processes models (spec 0028 #3).

Masters (#3.1) are seeded and edited in admin, retired with ``is_active``.
A police station is a ``locations.Location`` of type ``police_station``
(spec 0007 #9), the master every police channel chooses from (``PRC-08``).
"""

from functools import reduce
from operator import and_, or_

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseActivatableModel, BaseAuditableModel, BaseModel

from .enums import (
    SIGNED_STATUSES,
    DestinationKind,
    EventSource,
    ProcessStatus,
    RecipientType,
    Side,
    StepMode,
)

EVENT_IMMUTABLE_MESSAGE = "A process event is never changed once recorded."

# Where each destination kind keeps its value; a police station has none here.
DESTINATION_FIELDS = {
    DestinationKind.POSTAL: "address_id",
    DestinationKind.MOBILE: "mobile",
    DestinationKind.EMAIL: "email",
    DestinationKind.POLICE_STATION: None,
}
_EMPTY = {"address_id": Q(address_id__isnull=True), "mobile": Q(mobile=""), "email": Q(email="")}


def _destination_shape():
    """The field matching ``destination_kind`` is set and the others are empty (``PRC-05``)."""
    return reduce(
        or_,
        (
            reduce(
                and_,
                (~empty if name == field else empty for name, empty in _EMPTY.items()),
                Q(destination_kind=kind),
            )
            for kind, field in DESTINATION_FIELDS.items()
        ),
    )


class Master(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """A seeded, admin-edited row; retired, never deleted."""

    class Meta(BaseModel.Meta):
        """Meta options."""

        abstract = True


class ProcessType(Master):
    """Notice, summons, warrant, proclamation, attachment, custom process (``process.md`` §2)."""

    code = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=64)
    # The catalogue item that triggers it, e.g. ``ISSUE_OF_SUMMONS``.
    order_item_code = models.CharField(max_length=50, unique=True)
    positive_label = models.CharField(max_length=32)
    negative_label = models.CharField(max_length=32)
    # ``RecipientType`` values; backend configuration, not editable from the UI.
    allowed_recipient_types = models.JSONField(default=list)
    # The 0011 secondary stage; empty for custom process.
    stage_key = models.CharField(max_length=64, blank=True)

    class Meta(Master.Meta):
        """Meta options."""

        ordering = ("code",)

    def __str__(self):
        return self.label


class Channel(Master):
    """One way of delivering a process (§6.2, §13.1)."""

    code = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=64)
    destination_kind = models.CharField(max_length=16, choices=DestinationKind.choices)
    send_mode = models.CharField(max_length=8, choices=StepMode.choices)
    status_mode = models.CharField(max_length=8, choices=StepMode.choices)
    needs_envelope = models.BooleanField(default=False)
    is_police = models.BooleanField(default=False)
    # Offered in this deployment (``PRC-04``).
    is_available = models.BooleanField(default=True)

    class Meta(Master.Meta):
        """Meta options."""

        ordering = ("code",)

    def __str__(self):
        return self.label


class ProcessTypeChannel(Master):
    """A channel a process type may use, and whether it is preselected (§6.3, ``AUT-08``)."""

    process_type = models.ForeignKey(
        ProcessType, on_delete=models.PROTECT, related_name="type_channels"
    )
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="type_channels")
    preselected = models.BooleanField(default=False)

    class Meta(Master.Meta):
        """Meta options."""

        ordering = ("process_type__code", "channel__code")
        constraints = [
            models.UniqueConstraint(
                fields=("process_type", "channel"), name="processes_type_channel_unique"
            )
        ]

    def __str__(self):
        return f"{self.process_type_id} via {self.channel_id}"


class NonDeliveryReason(Master):
    """The state's reasons for a negative outcome (``DSP-09``)."""

    state_code = models.CharField(max_length=3)
    code = models.CharField(max_length=32)
    label = models.CharField(max_length=128)
    sequence = models.PositiveSmallIntegerField(default=0)

    class Meta(Master.Meta):
        """Meta options."""

        ordering = ("state_code", "sequence", "code")
        constraints = [
            models.UniqueConstraint(fields=("state_code", "code"), name="processes_reason_unique")
        ]

    def __str__(self):
        return self.label


class ProcessRound(BaseModel):
    """Every process one order started (``process.md`` §3, ``SVC-04``)."""

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="process_rounds")
    order_id = models.UUIDField(unique=True)
    # The order's new hearing, else the case's next hearing at trigger (``PRC-06``).
    hearing_id = models.UUIDField(null=True, blank=True)
    # That hearing's date when the round started; never updated.
    hearing_date = models.DateField(null=True, blank=True)
    # The case's courtroom; every action is checked here (#2.2).
    court_id = models.UUIDField(db_index=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("-created_at",)


class Process(BaseModel, BaseAuditableModel):
    """One process type, to one recipient, on one channel, at one destination (``PRC-02``).

    What it starts with never changes; status, steps and outcome are the rest
    of the row and its events. Written only by ``services``.
    """

    round = models.ForeignKey(ProcessRound, on_delete=models.PROTECT, related_name="processes")
    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="processes")
    order_item_id = models.UUIDField()
    process_type = models.ForeignKey(ProcessType, on_delete=models.PROTECT, related_name="+")
    channel = models.ForeignKey(Channel, on_delete=models.PROTECT, related_name="+")
    recipient_type = models.CharField(max_length=32, choices=RecipientType.choices)
    # The case participant.
    recipient_id = models.UUIDField()
    recipient_name = models.CharField(max_length=255)
    destination_kind = models.CharField(max_length=16, choices=DestinationKind.choices)
    address_id = models.UUIDField(null=True, blank=True)
    mobile = models.CharField(max_length=16, blank=True)
    email = models.EmailField(blank=True)
    police_station = models.ForeignKey(
        "locations.Location", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Added on the order screen rather than taken from the record (``PRC-05``).
    destination_added = models.BooleanField(default=False)
    party_taking_steps = models.CharField(max_length=16, choices=Side.choices)
    hearing_id = models.UUIDField(null=True, blank=True)

    status = models.CharField(max_length=24, choices=ProcessStatus.choices)
    status_at = models.DateTimeField()
    # The outcome comment, the recall comment, or the last error.
    remark = models.TextField(blank=True)
    reason = models.ForeignKey(
        NonDeliveryReason, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    outcome_file_id = models.CharField(max_length=64, blank=True)
    # The day it was delivered or executed, or the attempt failed, as reported.
    outcome_date = models.DateField(null=True, blank=True)

    court_fee = models.DecimalField(max_digits=18, decimal_places=2)
    fee_from_pool = models.DecimalField(max_digits=18, decimal_places=2)
    demand_item_id = models.UUIDField(null=True, blank=True, db_index=True)
    fee_paid = models.BooleanField(default=False)
    fee_paid_at = models.DateTimeField(null=True, blank=True)

    envelope_received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    envelope_received_at = models.DateTimeField(null=True, blank=True)

    signing_file_id = models.CharField(max_length=64, blank=True)
    signed_file_id = models.CharField(max_length=64, blank=True)
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    signed_at = models.DateTimeField(null=True, blank=True)
    signing_method = models.CharField(max_length=32, blank=True)

    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    provider_reference = models.CharField(max_length=128, blank=True)
    attempt = models.PositiveSmallIntegerField(default=1)

    # Applies only until the process is sent (``EXP-02``).
    expires_at = models.DateTimeField(null=True, blank=True)
    # Set on signing: the expiry no longer follows the hearing (``EXP-01a``).
    expiry_fixed = models.BooleanField(default=False)

    recalled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    recalled_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("created_at",)
        indexes = [
            models.Index(fields=("case", "status"), name="processes_case_status"),
            models.Index(fields=("status", "expires_at"), name="processes_expiry"),
            models.Index(fields=("channel", "status"), name="processes_channel_status"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "order_item_id",
                    "recipient_id",
                    "channel",
                    "address_id",
                    "mobile",
                    "email",
                    "police_station",
                ),
                nulls_distinct=False,
                name="processes_one_per_destination",
            ),
            models.CheckConstraint(
                condition=_destination_shape(), name="processes_destination_shape"
            ),
            models.CheckConstraint(
                condition=~Q(destination_kind=DestinationKind.POLICE_STATION)
                | Q(police_station__isnull=False),
                name="processes_police_needs_station",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=SIGNED_STATUSES) | ~Q(signed_file_id=""),
                name="processes_signed_has_file",
            ),
            models.CheckConstraint(
                condition=~Q(status=ProcessStatus.NOT_DELIVERED) | Q(reason__isnull=False),
                name="processes_negative_has_reason",
            ),
        ]

    def __str__(self):
        return f"{self.process_type_id} to {self.recipient_name} by {self.channel_id}"

    @property
    def status_label(self):
        """The status as the type names it: *Executed* for a warrant delivered (§10.1)."""
        if self.status == ProcessStatus.DELIVERED:
            return self.process_type.positive_label
        if self.status == ProcessStatus.NOT_DELIVERED:
            return self.process_type.negative_label
        return self.get_status_display()

    @property
    def steps_done(self):
        """Whether the fee is paid and the envelope, where one is needed, received (``STP-03``)."""
        return self.fee_paid and (
            not self.channel.needs_envelope or self.envelope_received_at is not None
        )


class ProcessEvent(BaseModel):
    """One status change, with its own time, so every stage is recorded apart (``SGN-04``)."""

    process = models.ForeignKey(Process, on_delete=models.PROTECT, related_name="events")
    # Empty for the creation event.
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, choices=ProcessStatus.choices)
    source = models.CharField(max_length=16, choices=EventSource.choices)
    # NULL for the system.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    at = models.DateTimeField()
    # Non-sensitive detail: reason code, comment, error code.
    data = models.JSONField(default=dict, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("at", "created_at")

    def save(self, *args, **kwargs):
        """Append only."""
        if not self._state.adding:
            raise ValueError(EVENT_IMMUTABLE_MESSAGE)
        super().save(*args, **kwargs)


class ProcessCaseLock(models.Model):
    """One row per case, locked so fan-out and fee allocation for a case run in turn (#12.4)."""

    case_id = models.UUIDField(unique=True)
