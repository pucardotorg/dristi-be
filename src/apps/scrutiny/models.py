"""Scrutiny models (spec 0024 #3)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseAuditableModel, BaseModel

from .checks.models import ScrutinyRuleBinding
from .enums import RoundDecision, RoundStage, RoutingReason

__all__ = ["ScrutinyRound", "ScrutinyRuleBinding"]


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
