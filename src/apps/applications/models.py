"""Applications models (spec 0033 #4).

Write only through ``apps.applications.services``: they lock the row, check the
transition table (#5.2), log every change in ``ApplicationTransition`` and keep
the tasks, demands and numbers in step. A value is a column only when it is
filtered, constrained, indexed or listed; who did what and when is a row of the
transition log (#4).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.models import (
    CODE_RE,
    BaseActivatableModel,
    BaseAuditableModel,
    BaseExtendableModel,
    BaseModel,
)

from .enums import (
    CIRCLE_ONLY_STATUSES,
    DECIDED_STATUSES,
    FILER_STATUSES,
    Action,
    ApplicationStatus,
    CounterKind,
    Outcome,
    Side,
    WorkflowStatus,
)

OBJECTION_CODE = "OBJECTION"

APPEND_ONLY_MESSAGE = "A transition is a log entry: it is never edited or deleted."
TYPE_CODE_FIXED_MESSAGE = "A type's code cannot change once created: applications store it."
TYPE_NOT_REGISTERED_MESSAGE = "No application type spec is registered for this code."
OBJECTION_TARGET_MESSAGE = "Set exactly when the application is an objection."
OBJECTION_SIDE_MESSAGE = "An objection is raised by the side opposite the application it answers."
OBJECTION_SELF_MESSAGE = "An application cannot object to itself."
SUBMITTED_ONLY_OBJECTION_MESSAGE = "Only an objection ends at Submitted."
HEARING_MESSAGE = "Set exactly when the type is about a hearing."


class ApplicationType(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """One kind of application, switched on for the deployment (#4.1).

    Its behaviour is the code spec registered for ``code`` (``types``); this row
    only labels, orders and activates it. Seeded from
    ``data/seed/core/applications/``; editable in admin except the code.
    """

    code = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=128)
    description = models.CharField(max_length=255, blank=True)
    template_code = models.CharField(
        max_length=64,
        blank=True,
        help_text="apps.pdf template key; blank renders with application-default (#6.5).",
    )
    sequence = models.PositiveSmallIntegerField(help_text="Order in the type picker.")

    class Meta:
        """Meta options."""

        ordering = ("sequence", "code")

    def __str__(self):
        return f"{self.label} ({self.code})"

    def clean(self):
        """The code is a registered spec's code, and never changes once created."""
        super().clean()
        from .types import registry

        if self.code and not CODE_RE.fullmatch(self.code):
            raise ValidationError({"code": "Must be uppercase snake_case, e.g. BAIL."})
        if self.code and registry.get(self.code) is None:
            raise ValidationError({"code": TYPE_NOT_REGISTERED_MESSAGE})
        if not self._state.adding:
            stored = type(self).objects.filter(pk=self.pk).values_list("code", flat=True).first()
            if stored is not None and stored != self.code:
                raise ValidationError({"code": TYPE_CODE_FIXED_MESSAGE})

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def spec(self):
        """The code spec of this type."""
        from .types import registry

        return registry.require(self.code)


class Application(BaseExtendableModel, BaseModel, BaseAuditableModel):
    """One application raised on a case (#4.2).

    ``data`` holds the type's own fields, validated by the type's spec;
    ``additional_attributes`` holds what a deployment declares without a
    release (#4.2.2).
    """

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="applications")
    application_type = models.ForeignKey(
        ApplicationType, on_delete=models.PROTECT, related_name="applications"
    )
    status = models.CharField(
        max_length=24, choices=ApplicationStatus.choices, default=ApplicationStatus.DRAFT
    )
    side = models.CharField(max_length=16, choices=Side.choices)
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="applications_raised",
        help_text="Application Raised By: the only person who signs it (ALC-28).",
    )
    raised_on_behalf_of = models.UUIDField(
        null=True, blank=True, help_text="The litigant: a CaseParticipant id."
    )
    details = models.TextField(blank=True, help_text="Sanitised rich text (#3.3.1).")
    data = models.JSONField(default=dict, blank=True)
    hearing_id = models.UUIDField(null=True, blank=True, db_index=True)
    objection_to = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="objection",
    )
    application_number = models.CharField(max_length=64, null=True, blank=True)
    earlier_application_number = models.CharField(max_length=64, null=True, blank=True)
    signing_file_id = models.CharField(max_length=64, blank=True)
    signed_file_id = models.CharField(max_length=64, blank=True)
    demand_id = models.UUIDField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    review_due_date = models.DateField(null=True, blank=True)
    decision_date = models.DateField(null=True, blank=True)
    objections_invited = models.BooleanField(null=True, blank=True)
    respond_by = models.DateField(null=True, blank=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices, blank=True)
    deciding_order_id = models.UUIDField(null=True, blank=True)
    workflow_status = models.CharField(
        max_length=16, choices=WorkflowStatus.choices, default=WorkflowStatus.NOT_APPLICABLE
    )
    version = models.PositiveIntegerField(default=0)

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["case", "application_number"],
                condition=Q(application_number__isnull=False),
                name="applications_number_unique_per_case",
            ),
            models.UniqueConstraint(
                fields=["case", "earlier_application_number"],
                condition=Q(earlier_application_number__isnull=False),
                name="applications_earlier_number_unique_per_case",
            ),
            # #4.2 also asks for the number here; a state taking numbers from CIS (#7)
            # submits before CIS returns one, so services.numbering enforces it instead.
            models.CheckConstraint(
                condition=Q(status__in=FILER_STATUSES) | Q(submitted_at__isnull=False),
                name="applications_submitted_at_from_submission",
            ),
            models.CheckConstraint(
                condition=Q(earlier_application_number__isnull=True)
                | Q(onboarded_at__isnull=False),
                name="applications_replaced_only_when_onboarded",
            ),
            models.CheckConstraint(
                condition=~Q(status=ApplicationStatus.DISMISSED) | Q(onboarded_at__isnull=True),
                name="applications_dismissed_before_onboarding",
            ),
            models.CheckConstraint(
                condition=~Q(status=ApplicationStatus.PENDING_DECISION)
                | Q(onboarded_at__isnull=False, decision_date__isnull=False),
                name="applications_pending_decision_onboarded",
            ),
            models.CheckConstraint(
                condition=(Q(outcome="") & ~Q(status__in=DECIDED_STATUSES))
                | Q(status__in=DECIDED_STATUSES, outcome=F("status")),
                name="applications_outcome_matches_status",
            ),
            # isnull=False: with no invitation, NULL = TRUE is NULL, and a NULL CHECK passes.
            models.CheckConstraint(
                condition=Q(respond_by__isnull=True)
                | Q(objections_invited__isnull=False, objections_invited=True),
                name="applications_respond_by_needs_invitation",
            ),
            models.CheckConstraint(
                condition=Q(status__in=CIRCLE_ONLY_STATUSES) | ~Q(signed_file_id=""),
                name="applications_signed_past_signature",
            ),
        ]
        indexes = [
            models.Index(fields=["case", "status"], name="applications_case_status_idx"),
            models.Index(fields=["status", "review_due_date"], name="applications_review_idx"),
            models.Index(fields=["status", "decision_date"], name="applications_decision_idx"),
            models.Index(fields=["application_type", "status"], name="applications_type_idx"),
            models.Index(fields=["hearing_id", "status"], name="applications_hearing_idx"),
            models.Index(fields=["earlier_application_number"], name="applications_earlier_idx"),
        ]

    def __str__(self):
        return self.application_number or f"{self.application_type.label} draft {self.pk}"

    def clean(self):
        """The rules between fields the database cannot see (#4.2)."""
        super().clean()
        if not self.application_type_id:
            return
        code = self.application_type.code
        is_objection = code == OBJECTION_CODE
        errors = {}
        if is_objection != bool(self.objection_to_id):
            errors["objection_to"] = OBJECTION_TARGET_MESSAGE
        elif is_objection:
            if self.objection_to_id == self.pk:
                errors["objection_to"] = OBJECTION_SELF_MESSAGE
            elif self.side and self.objection_to.side == self.side:
                errors["side"] = OBJECTION_SIDE_MESSAGE
        if self.status == ApplicationStatus.SUBMITTED and not is_objection:
            errors["status"] = SUBMITTED_ONLY_OBJECTION_MESSAGE
        if self.application_type.spec.needs_hearing != bool(self.hearing_id):
            errors["hearing_id"] = HEARING_MESSAGE
        if errors:
            raise ValidationError(errors)

    @property
    def spec(self):
        """The code spec of this application's type."""
        return self.application_type.spec

    @property
    def is_objection(self):
        return self.application_type.code == OBJECTION_CODE


class ApplicationDocument(BaseModel):
    """A file on an application (#4.3).

    A blank ``field_path`` is a supporting document named by the filer; a set
    one is the type field the file is attached to, named by the server.
    """

    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name="documents")
    field_path = models.CharField(max_length=128, blank=True)
    name = models.CharField(max_length=255)
    file_id = models.CharField(max_length=64)
    sequence = models.PositiveSmallIntegerField(default=0)

    class Meta:
        """Meta options."""

        ordering = ("sequence", "created_at")

    def __str__(self):
        return self.name

    @property
    def is_supporting(self):
        return not self.field_path


class TransitionQuerySet(models.QuerySet):
    """Refuses bulk edits and deletes: the log is append-only."""

    def update(self, **kwargs):
        raise ValidationError(APPEND_ONLY_MESSAGE)

    def delete(self):
        raise ValidationError(APPEND_ONLY_MESSAGE)


class ApplicationTransition(BaseModel):
    """One entry of the append-only log (#4.4).

    Every status change, every order that acts on the application, and every
    attempt at the type's workflow. The rows with an ``order_id`` are the
    application's *Orders* attribute (``ALC-33``). ``application`` is a
    ``SET_NULL`` foreign key so the ``DELETE`` row of a deleted draft survives
    it as an audit record (#6.5b); ``application_ref`` keeps the id.
    """

    application = models.ForeignKey(
        Application,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transitions",
    )
    application_ref = models.UUIDField(db_index=True)
    action = models.CharField(max_length=32, choices=Action.choices)
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="application_transitions",
    )
    order_id = models.UUIDField(null=True, blank=True)
    summary = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    objects = TransitionQuerySet.as_manager()

    class Meta:
        """Meta options."""

        ordering = ("created_at",)
        constraints = [
            # #4.4 asks for (application, order_id); #8.3 has one order that onboards
            # and decides write two rows. The action keeps both while still letting
            # an order do each act once; ``services.actions`` refuses a second run.
            models.UniqueConstraint(
                fields=["application_ref", "order_id", "action"],
                condition=Q(order_id__isnull=False),
                name="applications_one_act_per_order",
            ),
        ]

    def __str__(self):
        return f"{self.action} {self.from_status}->{self.to_status}"

    def save(self, *args, **kwargs):
        """Insert only."""
        if not self._state.adding:
            raise ValidationError(APPEND_ONLY_MESSAGE)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(APPEND_ONLY_MESSAGE)


class OfficeMembership(BaseModel, BaseActivatableModel):
    """PLACEHOLDER: a clerk or junior advocate working in an advocate's office (#1.2).

    Office access (``office-management-handover.md``, ``OFC-03``, ``OFC-06``) is
    not modelled anywhere yet, and a clerk cannot hold a ``Representation``. Until
    it is, an administrator records here who works for whom; ``ports.case_access``
    is the only reader. The member works for the advocate on every case the
    advocate holds an active representation on. Delete this model, and the port
    that reads it, when office access lands.
    """

    member = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="office_memberships"
    )
    advocate = models.ForeignKey(
        "users.AdvocateProfile", on_delete=models.CASCADE, related_name="office_members"
    )

    class Meta:
        """Meta options."""

        constraints = [
            models.UniqueConstraint(
                fields=["member", "advocate"],
                condition=Q(is_active=True),
                name="applications_office_membership_unique",
            ),
        ]

    def __str__(self):
        return f"{self.member} for {self.advocate}"


class ApplicationCounter(BaseModel):
    """The last number of one series (#4.5); locked while a number is allotted."""

    kind = models.CharField(max_length=16, choices=CounterKind.choices)
    scope_key = models.CharField(max_length=64)
    year = models.PositiveIntegerField(default=0)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        """Meta options."""

        constraints = [
            models.UniqueConstraint(
                fields=["kind", "scope_key", "year"], name="applications_counter_unique"
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.scope_key}/{self.year}: {self.last_number}"
