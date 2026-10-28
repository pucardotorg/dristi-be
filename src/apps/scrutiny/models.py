"""Scrutiny models (spec 0024 #3)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseAuditableModel, BaseModel

from .checks.models import ScrutinyRuleBinding
from .enums import (
    DocumentIssue,
    FlagStatus,
    FlagTarget,
    ResponseKind,
    RoundDecision,
    RoundStage,
    RoutingReason,
)

__all__ = ["ScrutinyFlag", "ScrutinyFlagResponse", "ScrutinyRound", "ScrutinyRuleBinding"]


class ScrutinyRound(BaseModel, BaseAuditableModel):
    """One entry of a case into the ``scrutiny`` or ``registration`` state (#3.1).

    Rounds are opened by the workflow's ``state_entered`` signal and decided
    through ``apps.scrutiny.services.rounds``; ``decision`` is empty while open.
    """

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="scrutiny_rounds")
    stage = models.CharField(max_length=16, choices=RoundStage.choices)
    number = models.PositiveSmallIntegerField(
        help_text="The workflow visit number of this state: round 1, 2, 3."
    )
    # The 0011 workflow visit; opening a round is idempotent on it (#4.1).
    visit_id = models.UUIDField(unique=True)
    establishment_id = models.UUIDField(
        db_index=True,
        help_text="The court establishment where scrutiny and registration happen.",
    )
    routing_reason = models.CharField(max_length=32, choices=RoutingReason.choices, blank=True)
    courtroom_id = models.UUIDField(
        null=True, blank=True, help_text="Chosen at Forward or Register; empty until then."
    )
    # Per-state values (SCR-13), so no choices; empty when the state has one type.
    registration_type = models.CharField(max_length=32, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    decision = models.CharField(max_length=16, choices=RoundDecision.choices, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    open_items_acknowledged = models.BooleanField(
        default=False, help_text="Forwarded or registered with unresolved flags."
    )
    open_items_at_decision = models.PositiveSmallIntegerField(default=0)
    comment = models.TextField(
        blank=True, help_text="The Case registerer's overall comment on a registration send back."
    )

    class Meta:
        """Meta options."""

        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("case", "stage", "number"),
                name="scrutiny_round_unique_number",
                violation_error_message="This case already has a round with this stage and number.",
            ),
            models.UniqueConstraint(
                fields=("case",),
                condition=Q(decision=""),
                name="scrutiny_round_one_open_per_case",
                violation_error_message="This case already has an open round.",
            ),
            models.CheckConstraint(
                check=Q(number__gte=1),
                name="scrutiny_round_number_positive",
                violation_error_message="Round numbers start at 1.",
            ),
        ]
        verbose_name = "Scrutiny round"
        verbose_name_plural = "Scrutiny rounds"

    def __str__(self):
        return f"{self.case} · {self.get_stage_display()} round {self.number}"

    @property
    def is_open(self):
        """Whether the round still awaits a decision."""
        return not self.decision

    def clean(self):
        """Keep the decision fields consistent with the stage and with each other."""
        super().clean()
        errors = {}
        if (self.started_by_id is None) != (self.started_at is None):
            errors["started_at"] = "Set together with started_by."
        decided = bool(self.decision)
        if decided != (self.decided_by_id is not None):
            errors["decided_by"] = "Set exactly when the round has a decision."
        if decided != (self.decided_at is not None):
            errors["decided_at"] = "Set exactly when the round has a decision."
        if self.decision == RoundDecision.FORWARDED and self.stage != RoundStage.SCRUTINY:
            errors["decision"] = "Only a scrutiny round can be forwarded."
        moves_on = self.decision in (RoundDecision.FORWARDED, RoundDecision.REGISTERED)
        if not moves_on and (self.open_items_acknowledged or self.open_items_at_decision):
            errors["open_items_acknowledged"] = (
                "Open items are recorded only when forwarding or registering."
            )
        elif self.open_items_at_decision and not self.open_items_acknowledged:
            errors["open_items_acknowledged"] = "Unresolved flags must be acknowledged."
        if self.comment and not (
            self.stage == RoundStage.REGISTRATION and self.decision == RoundDecision.SENT_BACK
        ):
            errors["comment"] = "Only a registration send back carries a comment."
        # A registration round copies them from the round that forwarded it (#4.1).
        if self.stage == RoundStage.SCRUTINY and not moves_on:
            if self.courtroom_id:
                errors["courtroom_id"] = "Chosen only at Forward or Register."
            if self.registration_type:
                errors["registration_type"] = "Chosen only at Forward or Register."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class ScrutinyFlag(BaseModel, BaseAuditableModel):
    """One item the court wants fixed: a field, section, document or oath (#3.2).

    Drafted, raised, responded to and resolved through
    ``apps.scrutiny.services.flags``; the lifecycle is in #3.5. Whether the
    target exists on the case is checked there, against the case-type plugin.
    """

    round = models.ForeignKey(ScrutinyRound, on_delete=models.CASCADE, related_name="flags")
    target_type = models.CharField(max_length=16, choices=FlagTarget.choices)
    target_ref = models.CharField(
        max_length=128,
        help_text="FIELD: field id with record index, e.g. CHQ-9[0]; SECTION: section code; "
        "DOCUMENT: case document id; OATH: oath id.",
    )
    target_label = models.CharField(max_length=255, help_text="Snapshot for history.")
    # Empty only for an oath, which is not a section of the form (#3.2).
    section_id = models.CharField(max_length=16, blank=True)
    reason_code = models.CharField(max_length=32, choices=DocumentIssue.choices, blank=True)
    note = models.TextField(blank=True, help_text="The note for the advocate.")
    value_at_flag = models.JSONField(null=True, blank=True)
    auto_marked_by = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="auto_marked_flags",
        help_text="The flag whose date chain marked this one (#3.3).",
    )
    linked_flag = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="A field flag and its document issue, saved together.",
    )
    carried_from = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="carried_to",
        help_text="The same item, still unresolved, in the previous round.",
    )
    status = models.CharField(max_length=16, choices=FlagStatus.choices)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        """Meta options."""

        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("round", "target_type", "target_ref"),
                condition=~Q(status=FlagStatus.WITHDRAWN),
                name="scrutiny_flag_one_live_per_target",
                violation_error_message="This target already has a live flag in this round.",
            ),
        ]
        verbose_name = "Scrutiny flag"
        verbose_name_plural = "Scrutiny flags"

    def __str__(self):
        return f"{self.get_target_type_display()} {self.target_ref} ({self.get_status_display()})"

    def clean(self):
        """Keep the flag consistent with its target type and with the flags it links to."""
        super().clean()
        errors = {}
        is_oath = self.target_type == FlagTarget.OATH
        if is_oath and self.section_id:
            errors["section_id"] = "An oath is not a section of the form."
        elif not is_oath and not self.section_id:
            errors["section_id"] = "This field is required."
        if self.reason_code and self.target_type != FlagTarget.DOCUMENT:
            errors["reason_code"] = "Only a document flag has a reason."
        # The screen's "No note — the advocate won't know what to fix" (E09004).
        if self.target_type == FlagTarget.DOCUMENT:
            if not self.reason_code and not self.note.strip():
                errors["note"] = "A document flag needs a reason or a note."
        elif self.target_type and not self.note.strip():
            errors["note"] = "A note for the advocate is required."
        if self.value_at_flag is not None and self.target_type != FlagTarget.FIELD:
            errors["value_at_flag"] = "Only a field flag records a value."
        resolved = self.status == FlagStatus.RESOLVED
        if resolved != (self.resolved_by_id is not None):
            errors["resolved_by"] = "Set exactly when the flag is resolved."
        if resolved != (self.resolved_at is not None):
            errors["resolved_at"] = "Set exactly when the flag is resolved."
        errors.update(self._clean_links())
        if errors:
            raise ValidationError(errors)

    def _clean_links(self):
        errors = {}
        if self.auto_marked_by_id:
            source = self.auto_marked_by
            if source.pk == self.pk:
                errors["auto_marked_by"] = "A flag cannot mark itself."
            elif source.round_id != self.round_id:
                errors["auto_marked_by"] = "Must be a flag of the same round."
            elif self.target_type != FlagTarget.FIELD or source.target_type != FlagTarget.FIELD:
                errors["auto_marked_by"] = "The date chain links field flags only."
        if self.linked_flag_id:
            linked = self.linked_flag
            if linked.pk == self.pk:
                errors["linked_flag"] = "A flag cannot link to itself."
            elif linked.round_id != self.round_id:
                errors["linked_flag"] = "Must be a flag of the same round."
            elif {self.target_type, linked.target_type} != {FlagTarget.FIELD, FlagTarget.DOCUMENT}:
                errors["linked_flag"] = "Links a field flag to a document issue."
        if self.carried_from_id and self.round_id:
            previous = self.carried_from
            if previous.round_id == self.round_id:
                errors["carried_from"] = "Must be a flag of another round."
            elif previous.round.case_id != self.round.case_id:
                errors["carried_from"] = "Must be a flag of the same case."
            elif (previous.target_type, previous.target_ref) != (
                self.target_type,
                self.target_ref,
            ):
                errors["carried_from"] = "Must be the same target."
        return errors

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class ScrutinyFlagResponse(BaseModel, BaseAuditableModel):
    """The filer's answer to a raised flag: a correction, a re-upload or an explanation (#3.6).

    Recorded by ``apps.scrutiny.services.responses`` from the ``apps.cases``
    change signals or the explain endpoint (#5.2). A flag may get several in
    one correction; history shows the last.
    """

    flag = models.ForeignKey(ScrutinyFlag, on_delete=models.CASCADE, related_name="responses")
    kind = models.CharField(max_length=16, choices=ResponseKind.choices)
    note = models.TextField(blank=True)
    value_after = models.JSONField(null=True, blank=True)
    document_id = models.UUIDField(null=True, blank=True, help_text="The new case document.")
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    responded_at = models.DateTimeField()

    class Meta:
        """Meta options."""

        ordering = ("responded_at",)
        verbose_name = "Scrutiny flag response"
        verbose_name_plural = "Scrutiny flag responses"

    def __str__(self):
        return f"{self.get_kind_display()} · {self.flag}"

    def clean(self):
        """Keep the response's payload consistent with its kind and its flag's target."""
        super().clean()
        errors = {}
        if self.kind == ResponseKind.EXPLAINED and not self.note.strip():
            errors["note"] = "An explanation needs a note."
        if self.value_after is not None and self.kind != ResponseKind.CORRECTED:
            errors["value_after"] = "Only a correction records a value."
        if (self.kind == ResponseKind.REUPLOADED) != (self.document_id is not None):
            errors["document_id"] = "Set exactly when a document was re-uploaded."
        if self.flag_id:
            # A field change answers its field flag or the section flag that holds it.
            target = self.flag.target_type
            if self.kind == ResponseKind.CORRECTED and target not in (
                FlagTarget.FIELD,
                FlagTarget.SECTION,
            ):
                errors["kind"] = "Only a field or section flag is corrected."
            elif self.kind == ResponseKind.REUPLOADED and target != FlagTarget.DOCUMENT:
                errors["kind"] = "Only a document flag is re-uploaded."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)
