"""Which business rule decides a scrutiny decision for a jurisdiction (spec 0024 #2.4)."""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import CODE_RE, BaseActivatableModel, BaseAuditableModel, BaseModel
from apps.scrutiny.enums import Decision


class ScrutinyRuleBinding(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """Binds a ``BusinessRule`` code to a decision for an organization and its subtree.

    Spec 0019 keeps one rule per code with no per-organization variants, so the
    jurisdiction lives here. ``organization`` NULL is the national default.
    Resolve through ``apps.scrutiny.checks.resolver``, not by querying this model.
    """

    decision = models.CharField(max_length=16, choices=Decision.choices)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="scrutiny_rule_bindings",
        help_text="The establishment or High Court this binding applies to. "
        "Empty for the national default.",
    )
    # A code, not a foreign key: rules are read only through BusinessRuleService.
    rule_code = models.CharField(max_length=50, help_text="A business rule code.")
    note = models.CharField(max_length=255, blank=True, help_text="Why this jurisdiction differs.")

    class Meta:
        """Meta options."""

        ordering = ("decision", "-created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("decision", "organization"),
                condition=Q(is_active=True),
                name="scrutiny_binding_one_active_per_organization",
                violation_error_message="An active binding for this decision and "
                "organization already exists.",
            ),
            # NULLs are distinct in a unique index, so the national default needs its own.
            models.UniqueConstraint(
                fields=("decision",),
                condition=Q(organization__isnull=True, is_active=True),
                name="scrutiny_binding_one_active_default",
                violation_error_message="An active national default for this decision "
                "already exists.",
            ),
        ]
        verbose_name = "Scrutiny rule binding"
        verbose_name_plural = "Scrutiny rule bindings"

    def __str__(self):
        where = self.organization.code if self.organization_id else "national default"
        return f"{self.decision} @ {where} -> {self.rule_code}"

    def clean(self):
        """Validate the rule code's format; the admin dry-runs the rule itself."""
        super().clean()
        if self.rule_code and not CODE_RE.fullmatch(self.rule_code):
            raise ValidationError(
                {"rule_code": "Must be uppercase snake_case matching ^[A-Z0-9_]+$."}
            )

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)
