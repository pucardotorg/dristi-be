"""Orders models (spec 0039 #3)."""

import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.core.models import (
    CODE_RE,
    BaseActivatableModel,
    BaseAuditableModel,
    BaseModel,
)

from . import field_schema
from .enums import (
    Availability,
    EnteredFrom,
    ItemCategory,
    ItemSource,
    NextHearingState,
    NumberSeries,
    OrderStatus,
    RoznamaStatus,
    RuleKind,
    RunStatus,
    RunStep,
    SigningMethod,
    TriggerPhase,
)

SIGNED_NEEDS_FILE_MESSAGE = "A signed order has a signed file."
TRIGGERED_NEEDS_DATA_MESSAGE = "A triggered order has its order data complete."
NEXT_HEARING_SHAPE_MESSAGE = "A listed next hearing has a date and a purpose; no other has either."
CODE_MESSAGE = "Use upper case letters, digits and underscores."


def _user(related_name="+"):
    return models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name=related_name,
    )


class OrderType(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """An order type a state offers and what it changes (spec 0039 #3.9, #2.2).

    Seeded from ``data/seed/core/orders/order_types.toml``; edited in admin and
    retired with ``is_active``. Each state has exactly one ``NORMAL``.
    """

    state_code = models.CharField(max_length=8)
    code = models.CharField(max_length=16)
    label = models.CharField(max_length=64)
    allows_linked_documents = models.BooleanField(default=True)
    separate_diary_entry = models.BooleanField(default=True)
    diary_entry_label = models.CharField(max_length=32)
    signs_diary_entry = models.BooleanField(
        default=False, help_text="Gujarat's Normal: the Roznama is signed as its own document."
    )
    diary_entry_in_a_diary = models.BooleanField(
        default=False,
        help_text="Kerala: after triggering, the A-Diary owns the entry and edits it (#6.6).",
    )
    number_series = models.CharField(
        max_length=16, choices=NumberSeries.choices, default=NumberSeries.ORDER
    )
    pdf_heading = models.CharField(max_length=32, default="Order")
    default_title = models.CharField(max_length=64)
    preselect_from = models.JSONField(
        default=list,
        blank=True,
        help_text="Where an order starts as this type: HEARING, APPLICATION_ONBOARDING.",
    )

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("state_code", "code")
        constraints = [
            models.UniqueConstraint(fields=["state_code", "code"], name="orders_type_unique"),
        ]

    def __str__(self):
        return f"{self.state_code} {self.label}"

    def clean(self):
        """Check that ``preselect_from`` is a list of known screens."""
        super().clean()
        known = {"HEARING", "APPLICATION_ONBOARDING"}
        if not isinstance(self.preselect_from, list) or any(
            not isinstance(screen, str) or screen not in known for screen in self.preselect_from
        ):
            raise ValidationError({"preselect_from": f"Use a list of {sorted(known)}."})
        if not self.separate_diary_entry and self.signs_diary_entry:
            raise ValidationError(
                {"signs_diary_entry": "A type with no separate diary entry has no Roznama."}
            )


class OrderItemType(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """One order item of the catalogue (spec 0039 #3.3).

    Seeded from ``order-template-catalogue.md`` by
    ``data/seed/core/orders/order_item_types.toml``; edited in admin; retired
    with ``is_active = False``, never deleted.
    """

    code = models.CharField(max_length=50, unique=True)
    label = models.CharField(max_length=128)
    category = models.CharField(max_length=32, choices=ItemCategory.choices, blank=True)
    availability = models.CharField(max_length=16, choices=Availability.choices)
    target_type = models.CharField(max_length=16, blank=True)
    field_schema = models.JSONField(default=dict)
    has_workflow = models.BooleanField(default=False)
    trigger_phase = models.CharField(
        max_length=8, choices=TriggerPhase.choices, default=TriggerPhase.NORMAL
    )
    stage_event = models.CharField(max_length=64, blank=True)
    closes_case = models.CharField(max_length=32, blank=True)
    outcome = models.CharField(max_length=16, blank=True)
    suggested_for_purposes = models.ManyToManyField(
        "hearings.HearingPurpose", blank=True, related_name="suggested_order_items"
    )
    sequence = models.PositiveSmallIntegerField(default=0)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("category", "sequence", "code")

    def __str__(self):
        return self.code

    def clean(self):
        """Check the code, the field schema and the contextual target."""
        super().clean()
        errors = {}
        if not CODE_RE.fullmatch(self.code or ""):
            errors["code"] = CODE_MESSAGE
        if problems := field_schema.schema_errors(self.field_schema):
            errors["field_schema"] = " ".join(problems)
        if self.availability != Availability.DROPDOWN and self.target_type != "APPLICATION":
            errors["target_type"] = "A contextual item applies to an APPLICATION."
        if self.availability == Availability.CONTEXTUAL and self.category:
            errors["category"] = "A contextual item has no category."
        if errors:
            raise ValidationError(errors)


class OrderItemCombinationRule(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """One restriction of the catalogue's *Combination restrictions* (spec 0039 #3.4, ``ITM-07``)."""

    code = models.CharField(max_length=50, unique=True)
    kind = models.CharField(max_length=16, choices=RuleKind.choices)
    item_types = models.ManyToManyField(OrderItemType, related_name="combination_rules")
    message = models.CharField(
        max_length=255, help_text="May use {adding} and {existing}: the two items' labels."
    )

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("code",)

    def __str__(self):
        return self.code

    def clean(self):
        """Check the message uses only the two documented placeholders."""
        super().clean()
        try:
            names = [
                name for _, name, _, _ in string.Formatter().parse(self.message) if name is not None
            ]
            ok = set(names) <= {"adding", "existing"}
            # Also catches what parsing alone allows, such as a nested ``{adding:{x}}``.
            self.message.format(adding="", existing="")
        except (ValueError, KeyError, IndexError, AttributeError):
            ok = False
        if not ok:
            raise ValidationError(
                {
                    "message": "Use only the placeholders {adding} and {existing}, with braces closed."
                }
            )


class Order(BaseModel, BaseAuditableModel):
    """One order of one case, in a hearing or outside one (spec 0039 #3.1).

    Write only through ``apps.orders.services``, which lock the order and check
    the lifecycle (#4, #12.5). The text and the order data are worked
    separately and carry separate versions (#5.4).
    """

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="orders")
    court = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="orders"
    )
    hearing = models.ForeignKey(
        "hearings.Hearing", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    order_type = models.ForeignKey(OrderType, on_delete=models.PROTECT, related_name="orders")
    title = models.CharField(max_length=255)
    title_overridden = models.BooleanField(default=False)
    text = models.TextField(blank=True)
    text_version = models.PositiveIntegerField(default=0)
    data_version = models.PositiveIntegerField(default=0)
    text_saved_by = _user()
    text_saved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=OrderStatus.choices, default=OrderStatus.DRAFT)
    data_complete = models.BooleanField(default=False)
    data_completed_by = _user()
    data_completed_at = models.DateTimeField(null=True, blank=True)

    next_hearing_state = models.CharField(
        max_length=16, choices=NextHearingState.choices, default=NextHearingState.UNSET
    )
    next_hearing_date = models.DateField(null=True, blank=True)
    next_hearing_purpose = models.CharField(max_length=50, blank=True)
    moves_hearing_id = models.UUIDField(null=True, blank=True)
    next_hearing_held = models.BooleanField(
        default=False,
        help_text="A provisional hearing in apps.hearings holds this order's date.",
    )
    next_hearing_entered_from = models.CharField(
        max_length=16, choices=EnteredFrom.choices, blank=True
    )
    next_hearing_entered_by = _user()
    next_hearing_entered_at = models.DateTimeField(null=True, blank=True)

    diary_same_as_text = models.BooleanField(default=True)
    diary_text = models.TextField(blank=True)

    sent_for_signing_by = _user()
    sent_for_signing_at = models.DateTimeField(null=True, blank=True)
    number = models.CharField(max_length=128, blank=True)
    order_date = models.DateField(null=True, blank=True)
    signing_file_id = models.CharField(max_length=64, blank=True)
    signing_heading = models.CharField(
        max_length=32,
        blank=True,
        help_text="The heading printed on the file prepared for signing; signed reads keep it.",
    )
    signing_attendance = models.JSONField(
        default=list,
        blank=True,
        help_text="The attendance lines printed on the file prepared for signing.",
    )
    signed_file_id = models.CharField(max_length=64, blank=True)
    signing_method = models.CharField(max_length=16, choices=SigningMethod.choices, blank=True)
    signed_by = _user()
    signed_at = models.DateTimeField(null=True, blank=True)
    signer_designation = models.CharField(max_length=128, blank=True)
    triggered_at = models.DateTimeField(null=True, blank=True)
    discarded_by = _user()
    discarded_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["hearing"],
                condition=Q(hearing__isnull=False) & ~Q(status=OrderStatus.DISCARDED),
                name="orders_one_per_hearing",
            ),
            models.UniqueConstraint(
                fields=["number"], condition=~Q(number=""), name="orders_number_unique"
            ),
            models.CheckConstraint(
                condition=~Q(status__in=(OrderStatus.SIGNED, OrderStatus.TRIGGERED))
                | ~Q(signed_file_id=""),
                name="orders_signed_has_file",
                violation_error_message=SIGNED_NEEDS_FILE_MESSAGE,
            ),
            models.CheckConstraint(
                condition=~Q(status=OrderStatus.TRIGGERED) | Q(data_complete=True),
                name="orders_triggered_is_complete",
                violation_error_message=TRIGGERED_NEEDS_DATA_MESSAGE,
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        next_hearing_state=NextHearingState.LISTED,
                        next_hearing_date__isnull=False,
                    )
                    & ~Q(next_hearing_purpose="")
                )
                | (
                    ~Q(next_hearing_state=NextHearingState.LISTED)
                    & Q(next_hearing_date__isnull=True, next_hearing_purpose="")
                ),
                name="orders_next_hearing_shape",
                violation_error_message=NEXT_HEARING_SHAPE_MESSAGE,
            ),
        ]
        indexes = [
            models.Index(fields=["court", "status"], name="orders_court_status_idx"),
            models.Index(fields=["case", "-created_at"], name="orders_case_created_idx"),
            models.Index(fields=["court", "data_complete", "status"], name="orders_court_data_idx"),
        ]

    def __str__(self):
        return f"{self.title} ({self.case_id})"

    @property
    def is_signed(self):
        """Whether a signature has been recorded."""
        return self.status in (OrderStatus.SIGNED, OrderStatus.TRIGGERED)


class OrderItem(BaseModel, BaseAuditableModel):
    """An order item on an order, with its values (spec 0039 #3.2)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    item_type = models.ForeignKey(OrderItemType, on_delete=models.PROTECT, related_name="items")
    position = models.PositiveSmallIntegerField()
    target_type = models.CharField(max_length=16, blank=True)
    target_id = models.UUIDField(null=True, blank=True)
    values = models.JSONField(default=dict, blank=True)
    added_by_source = models.CharField(
        max_length=16, choices=ItemSource.choices, default=ItemSource.PERSON
    )
    confirmed = models.BooleanField(default=True)
    unconfirmed_fields = models.JSONField(default=list, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("order", "position")
        constraints = [
            models.UniqueConstraint(fields=["order", "position"], name="orders_item_position"),
        ]

    def __str__(self):
        return f"{self.item_type_id} #{self.position}"


class OrderLinkedDocument(BaseModel):
    """A case document linked to an order (spec 0039 #3.5, ``ORD-17``)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="linked_documents")
    document_id = models.UUIDField()

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.UniqueConstraint(fields=["order", "document_id"], name="orders_link_unique"),
        ]


class OrderShortcut(BaseModel, BaseAuditableModel):
    """A person's own text shortcut (spec 0039 #3.6, ``SHC-``).

    ``scope`` lists the screens it is offered on (a JSON list: the portable
    stand-in for the spec's ``ArrayField``, which SQLite does not have).
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shortcuts"
    )
    name = models.CharField(max_length=64)
    body = models.TextField()
    scope = models.JSONField(default=list)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(Lower("name"), "owner", name="orders_shortcut_name_unique"),
        ]

    def __str__(self):
        return self.name


class OrderRoznama(BaseModel, BaseAuditableModel):
    """The Roznama of a normal order in Gujarat: its own signed document (spec 0039 #3.10)."""

    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="roznama")
    status = models.CharField(
        max_length=18, choices=RoznamaStatus.choices, default=RoznamaStatus.AWAITING_SIGNATURE
    )
    number = models.CharField(max_length=128, blank=True)
    signing_file_id = models.CharField(max_length=64, blank=True)
    signed_file_id = models.CharField(max_length=64, blank=True)
    signing_method = models.CharField(max_length=16, choices=SigningMethod.choices, blank=True)
    signed_by = _user()
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.UniqueConstraint(
                fields=["number"], condition=~Q(number=""), name="orders_roznama_number_unique"
            ),
            models.CheckConstraint(
                condition=~Q(status=RoznamaStatus.SIGNED) | ~Q(signed_file_id=""),
                name="orders_roznama_signed_has_file",
            ),
        ]


class OrderWorkflowRun(BaseModel):
    """One step of an order's triggering (spec 0039 #3.7, #9).

    Append-only except for status, attempts and result; never deleted.
    """

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="runs")
    order_item = models.ForeignKey(
        OrderItem, null=True, blank=True, on_delete=models.PROTECT, related_name="runs"
    )
    step = models.CharField(max_length=16, choices=RunStep.choices)
    sequence = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=16, choices=RunStatus.choices, default=RunStatus.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True)

    class Meta(BaseModel.Meta):
        """Meta options."""

        ordering = ("order", "sequence")
        constraints = [
            models.UniqueConstraint(fields=["order", "sequence"], name="orders_run_sequence"),
        ]

    def __str__(self):
        return f"{self.order_id} #{self.sequence} {self.step} {self.status}"


class OrderNumberCounter(BaseModel):
    """The last order or Roznama number allotted in a courtroom and year (spec 0039 #3.8)."""

    court = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="order_counters"
    )
    series = models.CharField(max_length=16, choices=NumberSeries.choices)
    year = models.PositiveIntegerField()
    last_value = models.PositiveIntegerField(default=0)

    class Meta(BaseModel.Meta):
        """Meta options."""

        constraints = [
            models.UniqueConstraint(fields=["court", "series", "year"], name="orders_counter"),
        ]
