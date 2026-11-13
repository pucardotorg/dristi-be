"""Shared base model used across the project."""

import copy
import re
import uuid

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models
from django.db.models import Q
from simple_history.models import HistoricalRecords

from .validators import (
    DATA_TYPE_CHOICES,
    coerce_value,
    validate_attribute_name,
    validate_default_value,
)

# Used with fullmatch(): "$" would also accept a trailing newline.
CODE_RE = re.compile(r"[A-Z0-9_]+")


class ActivatableQuerySet(models.QuerySet):
    """QuerySet helpers for models with an is_active flag."""

    def active(self):
        """Return rows with is_active=True."""
        return self.filter(is_active=True)

    def inactive(self):
        """Return rows with is_active=False."""
        return self.filter(is_active=False)


class BaseActivatableModel(models.Model):
    """Abstract mixin that adds an opt-in is_active flag."""

    is_active = models.BooleanField(default=True)

    objects = ActivatableQuerySet.as_manager()

    class Meta:
        """Meta options."""

        abstract = True


class BaseModel(models.Model):
    """Abstract base model with UUID primary key, timestamps, and audit users."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        default=None,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_created_by",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        default=None,
        blank=True,
        null=True,
        related_name="%(app_label)s_%(class)s_updated_by",
    )

    class Meta:
        """Meta options."""

        abstract = True
        ordering = ("-created_at",)


class BaseExtendableModel(models.Model):
    """Abstract base model that supports typed additional attributes."""

    additional_attributes = models.JSONField(default=dict, blank=True)

    class Meta:
        """Meta options."""

        abstract = True

    def full_clean(self, *args, **kwargs):
        """Coerce additional attributes before JSONField validation runs."""
        self.additional_attributes = self._clean_additional_attributes()
        super().full_clean(*args, **kwargs)

    def clean(self):
        """Validate and coerce additional attributes against their definitions."""
        super().clean()
        self.additional_attributes = self._clean_additional_attributes()

    def _clean_additional_attributes(self):
        """Return a cleaned dict of additional attributes for this instance."""
        content_type = ContentType.objects.get_for_model(self)
        definitions = {
            attr.name: attr
            for attr in AdditionalAttribute.objects.filter(content_type=content_type)
        }

        unknown = sorted(key for key in self.additional_attributes if key not in definitions)
        if unknown:
            raise ValidationError(
                {
                    "additional_attributes": (
                        f"Unknown additional attribute(s): {', '.join(unknown)}"
                    )
                }
            )

        cleaned = {}
        errors = {}
        for name, attr in definitions.items():
            if name in self.additional_attributes:
                value = self.additional_attributes[name]
            else:
                if attr.default_value is not None:
                    value = copy.deepcopy(attr.default_value)
                elif attr.is_nullable:
                    value = None
                else:
                    errors[name] = f"Missing required attribute: {name}"
                    continue

            if value is None:
                if not attr.is_nullable:
                    errors[name] = f"{name}: null value is not allowed"
                else:
                    cleaned[name] = None
                continue

            try:
                cleaned[name] = coerce_value(value, attr.data_type)
            except ValidationError as exc:
                message = exc.messages[0] if exc.messages else str(exc)
                errors[name] = f"{name}: {message}"

        if errors:
            raise ValidationError({"additional_attributes": list(errors.values())})

        return cleaned

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class BaseAuditableModel(models.Model):
    """Abstract base model that captures a full history table for every change."""

    history = HistoricalRecords(inherit=True)

    class Meta:
        abstract = True


class AdditionalAttribute(BaseModel, BaseAuditableModel):
    """Metadata describing an additional attribute available on a model."""

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="additional_attributes",
    )
    name = models.CharField(max_length=255)
    data_type = models.CharField(
        max_length=50,
        choices=DATA_TYPE_CHOICES,
    )
    is_nullable = models.BooleanField(default=True)
    default_value = models.JSONField(null=True, blank=True, default=None)

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        unique_together = ("content_type", "name")
        verbose_name = "Additional Attribute"
        verbose_name_plural = "Additional Attributes"

    def full_clean(self, *args, **kwargs):
        """Coerce default_value before JSONField validation runs."""
        if self.default_value is not None:
            self.default_value = coerce_value(self.default_value, self.data_type)
        super().full_clean(*args, **kwargs)

    def clean(self):
        """Validate the attribute name, data type, and default value."""
        super().clean()
        validate_attribute_name(self.name)
        if self.default_value is not None:
            validate_default_value(self.default_value, self.data_type)
        if not self.is_nullable and self.default_value is None:
            raise ValidationError("Non-nullable attributes must have a non-null default value.")

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class ApiVersionChangeLog(BaseExtendableModel, BaseModel, BaseActivatableModel, BaseAuditableModel):
    """API version change-log entry that uses BaseExtendableModel."""

    version = models.CharField(max_length=50)
    change_log = models.TextField()

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        verbose_name = "API Version Change Log"
        verbose_name_plural = "API Version Change Logs"


CONFIG_NAME_PATTERN = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)*$")


def normalize_config_name(value: str) -> str:
    """Return a configuration set/key trimmed and lowercased."""
    return value.strip().lower() if isinstance(value, str) else value


class Configuration(BaseModel, BaseActivatableModel):
    """A non-sensitive, runtime-editable key/value configuration entry.

    Values are opaque strings; read them through ``apps.core.services`` rather
    than querying this model directly. Secrets MUST NOT be stored here.
    """

    config_set = models.CharField(max_length=100)
    config_key = models.CharField(max_length=255)
    config_value = models.TextField(blank=True)
    description = models.TextField(null=True, blank=True)

    class Meta:
        """Meta options."""

        ordering = ("config_set", "config_key")
        constraints = [
            models.UniqueConstraint(
                fields=("config_set", "config_key"),
                name="core_configuration_unique_set_key",
            ),
        ]
        indexes = [
            models.Index(fields=("config_set",), name="core_config_set_idx"),
        ]
        verbose_name = "Configuration"
        verbose_name_plural = "Configurations"

    def __str__(self):
        return f"{self.config_set}.{self.config_key}"

    def clean(self):
        """Normalize the set and key, then validate their format."""
        super().clean()
        self.config_set = normalize_config_name(self.config_set)
        self.config_key = normalize_config_name(self.config_key)
        errors = {}
        for field in ("config_set", "config_key"):
            if not CONFIG_NAME_PATTERN.match(getattr(self, field) or ""):
                errors[field] = (
                    "Use lowercase letters, numbers, and underscores, optionally "
                    "grouped with dots (for example 'gateway.cdac.timeout')."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


class BusinessRule(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """A business rule evaluated in-process by one of the supported engines (spec 0019).

    Consumers evaluate rules through ``apps.core.rules.services.BusinessRuleService``
    only; they never query this model directly.
    """

    class RuleEngineType(models.TextChoices):
        """Engines that can evaluate ``rule_expression``."""

        RULE_ENGINE = "rule_engine", "Rule Engine"
        GORULES = "gorules", "GoRules"

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    engine = models.CharField(max_length=50, choices=RuleEngineType.choices, db_index=True)
    rule_expression = models.TextField()
    rule_input_schema = models.JSONField()
    rule_output_schema = models.JSONField()

    class Meta:
        """Meta options."""

        ordering = ("code",)
        verbose_name = "Business Rule"
        verbose_name_plural = "Business Rules"

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.name} ({self.code})"

    def clean(self):
        """Validate the code, the expression size, both schemas, and expression/schema agreement."""
        # Imported here: the rules package imports this module.
        from .rules.exceptions import EngineNotAvailable, RuleDefinitionError, RuleSchemaError
        from .rules.services import BusinessRuleService

        super().clean()
        # Fields that already failed form validation hold stale values here.
        excluded = getattr(self, "_clean_exclude", set())
        errors = {}
        if "code" not in excluded and (not self.code or not CODE_RE.fullmatch(self.code)):
            errors["code"] = "Must be uppercase snake_case matching ^[A-Z0-9_]+$ (e.g. COURT_FEE)."
        if "engine" not in excluded and self.engine not in self.RuleEngineType.values:
            errors["engine"] = f"Must be one of: {', '.join(self.RuleEngineType.values)}."
        expression = self.rule_expression or ""
        if "rule_expression" not in excluded:
            if not expression.strip():
                errors["rule_expression"] = "A rule expression is required."
            elif len(expression.encode("utf-8")) > settings.RULES_MAX_EXPRESSION_BYTES:
                errors["rule_expression"] = (
                    f"Expression is larger than {settings.RULES_MAX_EXPRESSION_BYTES} bytes."
                )
        for field in ("rule_input_schema", "rule_output_schema"):
            value = getattr(self, field)
            if field not in excluded and (not isinstance(value, dict) or not value):
                errors[field] = "A non-empty JSON Schema object is required."

        rule_fields = {"engine", "rule_expression", "rule_input_schema", "rule_output_schema"}
        if not (errors.keys() | excluded) & rule_fields:
            try:
                BusinessRuleService.validate_rule(self)
            except RuleSchemaError as exc:
                errors[exc.field] = str(exc)
            except (RuleDefinitionError, EngineNotAvailable) as exc:
                errors["rule_expression"] = str(exc)

        if errors:
            raise ValidationError(errors)

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
        """Let clean() skip the fields the caller excluded.

        A ModelForm excludes fields that already failed form validation. Those
        fields were never assigned to the instance, so re-checking them in
        clean() would report a misleading second error (or, on an edit,
        silently re-validate the old value).
        """
        self._clean_exclude = set(exclude or ())
        try:
            super().full_clean(
                exclude=exclude,
                validate_unique=validate_unique,
                validate_constraints=validate_constraints,
            )
        finally:
            del self._clean_exclude

    def save(self, *args, **kwargs):
        """Validate the model before saving, so no write path stores a broken rule."""
        self.full_clean()
        super().save(*args, **kwargs)


# BCP 47 tag, lowercase. Used with fullmatch(): "$" would also accept a trailing newline.
LANGUAGE_CODE_RE = re.compile(r"[a-z]{2,3}(-[a-z0-9]{2,8})*")


def validate_language_code(value):
    """Reject anything but a lowercase BCP 47 tag such as ``en`` or ``en-in``."""
    if not isinstance(value, str) or not LANGUAGE_CODE_RE.fullmatch(value):
        raise ValidationError(
            "Use a lowercase BCP 47 language tag, for example 'en', 'ml' or 'en-in'.",
            code="invalid",
        )


class LanguageQuerySet(ActivatableQuerySet):
    """QuerySet for supported languages."""

    def get_default(self):
        """Return the default (fallback) language.

        Raises ``ImproperlyConfigured`` when none is marked default: every
        language-aware endpoint falls back to it, so it must always exist.
        """
        try:
            return self.get(is_default=True)
        except self.model.DoesNotExist:
            raise ImproperlyConfigured("No default language is configured.") from None

    def bulk_create(self, objs, *args, **kwargs):
        """Normalise each language as ``save()`` does; bulk inserts skip ``save()``."""
        objs = list(objs)
        for obj in objs:
            obj.normalize()
        return super().bulk_create(objs, *args, **kwargs)

    def delete(self):
        """Refuse a bulk delete that includes the default language."""
        Language.check_deletable(self.filter(is_default=True).first())
        return super().delete()

    delete.alters_data = True
    delete.queryset_only = True


class Language(BaseModel, BaseActivatableModel):
    """A language Dristi supports, managed in admin (spec 0030).

    Shared reference data: consumers such as CMS (spec 0018) import it from
    here. Exactly one active row is the default, the fallback when a request
    names no supported language. ``supports`` lists the capabilities this
    language has; it is metadata for clients and features and does not gate
    language resolution, which only considers ``is_active``.
    """

    class LanguageSupport(models.TextChoices):
        """Capabilities a language can declare in ``supports``."""

        UI = "ui", "UI"
        TRANSLATION = "translation", "Translation"
        OCR = "ocr", "OCR"

    code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        validators=[validate_language_code],
        help_text="Lowercase BCP 47 tag, for example 'en', 'ml' or 'en-in'.",
    )
    name = models.CharField(max_length=100, help_text="English name, for example 'Malayalam'.")
    native_name = models.CharField(
        max_length=100, help_text="Name in the language itself, shown in language pickers."
    )
    is_default = models.BooleanField(
        default=False, help_text="The fallback language. Exactly one language is the default."
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    supports = models.JSONField(
        default=list,
        blank=True,
        help_text="Capabilities this language has. Empty means content-only.",
    )

    objects = LanguageQuerySet.as_manager()

    class Meta:
        """Meta options."""

        ordering = ("sort_order", "code")
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"],
                condition=Q(is_default=True),
                name="core_language_single_default",
                violation_error_message=(
                    "Another language is already the default. Use the "
                    "'Make default' action to switch the default language."
                ),
            ),
            models.CheckConstraint(
                condition=Q(is_default=False) | Q(is_active=True),
                name="core_language_default_is_active",
                violation_error_message="The default language must be active.",
            ),
        ]
        verbose_name = "Language"
        verbose_name_plural = "Languages"

    def __str__(self):
        return f"{self.name} ({self.code})"

    @classmethod
    def normalize_supports(cls, value):
        """Return ``value`` deduplicated and in ``LanguageSupport`` order.

        Raises ``ValidationError`` for non-list input or unknown capabilities.
        """
        if not isinstance(value, list):
            raise ValidationError({"supports": "Must be a list of capabilities."})
        unknown = [item for item in value if item not in cls.LanguageSupport.values]
        if unknown:
            raise ValidationError(
                {
                    "supports": (
                        f"Unknown capabilities: {', '.join(map(str, unknown))}. Use: "
                        f"{', '.join(cls.LanguageSupport.values)}."
                    )
                }
            )
        return [item for item in cls.LanguageSupport.values if item in value]

    def full_clean(self, *args, **kwargs):
        """Lowercase the code before field validation, so 'en-IN' is accepted as 'en-in'."""
        self._normalize_code()
        super().full_clean(*args, **kwargs)

    def clean(self):
        """Normalise the code and validate ``supports`` and the default language's state."""
        super().clean()
        self._normalize_code()
        errors = {}

        try:
            supports = self.normalize_supports(self.supports)
        except ValidationError as exc:
            errors.update(exc.message_dict)
        else:
            if len(supports) != len(self.supports):
                errors["supports"] = "Each capability may be listed only once."
            else:
                self.supports = supports

        if self.is_default and not self.is_active:
            errors["is_active"] = "The default language cannot be deactivated."
        if (
            not self.is_default
            and not self._state.adding
            and Language.objects.filter(pk=self.pk, is_default=True).exists()
        ):
            errors["is_default"] = (
                "This is the default language. Make another language the default instead."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Normalise before writing; ``bulk_create`` does the same."""
        self.normalize()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refuse to delete the default language.

        Checked against the database: this instance's ``is_default`` may be
        stale if the default moved after it was loaded.
        """
        self.check_deletable(Language.objects.filter(pk=self.pk, is_default=True).first())
        return super().delete(*args, **kwargs)

    def normalize(self):
        """Lowercase the code and put ``supports`` in enum order, deduplicated.

        Raises ``ValidationError`` for unknown capabilities or non-list ``supports``.
        """
        self._normalize_code()
        self.supports = self.normalize_supports(self.supports)

    @staticmethod
    def check_deletable(default):
        """Raise ``ProtectedError`` if ``default`` (the default language, or None) would go."""
        if default is not None:
            raise models.ProtectedError(
                "The default language cannot be deleted. Make another language the default first.",
                {default},
            )

    def _normalize_code(self):
        if isinstance(self.code, str):
            self.code = self.code.strip().lower()
