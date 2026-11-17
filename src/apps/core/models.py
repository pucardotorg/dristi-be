"""Shared base model used across the project."""

import copy
import json
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models
from django.db.models import Q
from simple_history.models import HistoricalRecords

from .validators import (
    DATA_TYPE_CHOICES,
    coerce_integer,
    coerce_value,
    parse_config_bool,
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


# Attribute definitions by content type id, while ``cached_attribute_definitions``
# is active; None otherwise, so every validation reads them fresh.
_attribute_definitions = ContextVar("attribute_definitions", default=None)


@contextmanager
def cached_attribute_definitions():
    """Read each model's additional attribute definitions once inside the block.

    A bulk load validates thousands of rows of one model; without this each
    row's ``full_clean`` queries the same definitions again. Use it only where
    definitions do not change inside the block.
    """
    token = _attribute_definitions.set({})
    try:
        yield
    finally:
        _attribute_definitions.reset(token)


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
        cache = _attribute_definitions.get()
        definitions = cache.get(content_type.pk) if cache is not None else None
        if definitions is None:
            definitions = {
                attr.name: attr
                for attr in AdditionalAttribute.objects.filter(content_type=content_type)
            }
            if cache is not None:
                cache[content_type.pk] = definitions

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


CONFIG_NAME_MESSAGE = (
    "Use lowercase letters, numbers, and underscores, optionally "
    "grouped with dots (for example 'gateway.cdac.timeout')."
)


def normalize_config_name(value: str) -> str:
    """Return a configuration set/key trimmed and lowercased."""
    return value.strip().lower() if isinstance(value, str) else value


def clean_config_names(instance) -> dict[str, str]:
    """Normalize ``config_set`` / ``config_key`` in place; return format errors by field."""
    errors = {}
    for field in ("config_set", "config_key"):
        value = normalize_config_name(getattr(instance, field))
        setattr(instance, field, value)
        if not CONFIG_NAME_PATTERN.match(value or ""):
            errors[field] = CONFIG_NAME_MESSAGE
    return errors


def check_other_config_store(instance, other_model, errors: dict[str, str]) -> None:
    """Add an error when the set/key pair already exists in ``other_model``.

    A pair belongs to exactly one of ``Configuration`` and
    ``PublicConfiguration`` (spec 0034 section 1.3). Inactive rows count, as
    they do for uniqueness. Application-level only: two concurrent saves of
    the same pair into both tables are not prevented.

    Only a new row or a changed pair is checked, so a row whose pair already
    ended up in both stores (bulk writes, a race, a manual fix) can still be
    edited or deactivated rather than only deleted.
    """
    if errors.keys() & {"config_set", "config_key"}:
        return
    pair = {"config_set": instance.config_set, "config_key": instance.config_key}
    if not instance._state.adding:
        stored = type(instance).objects.filter(pk=instance.pk).values(*pair).first()
        if stored == pair:
            return
    if other_model.objects.filter(**pair).exists():
        errors["config_key"] = (
            f"{instance.config_set}.{instance.config_key} already exists in "
            f"{other_model._meta.verbose_name}; a key belongs to exactly one store."
        )


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
        """Normalize and validate the set and key; reject a pair held in PublicConfiguration."""
        super().clean()
        errors = clean_config_names(self)
        check_other_config_store(self, PublicConfiguration, errors)
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        """Validate the model before saving."""
        self.full_clean()
        super().save(*args, **kwargs)


PUBLIC_CONFIGURATION_WARNING = "Everything in this table is public and visible to internet clients."

# Names that suggest a secret (spec 0034 section 1.4). Within each dotted part
# of a public set or key, one of these as an underscored run of words is
# rejected unless it only leads the part as a qualifier: ``client_secret_value``
# and ``gateway.password`` are rejected, ``token_expiry_minutes`` is not.
# Defence in depth only: a human still reviews every value.
#
# Consequence: a harmless name that mentions a secret word after its first
# word is rejected too, for example ``enable_password_reset`` or
# ``max_token_count``. Rename such a key so the word leads its part
# (``password_reset_enabled``, ``token_max_count``).
# This false positive is accepted over letting ``client_secret_value`` through.
SECRET_CONFIG_NAMES = frozenset(
    {
        "secret",
        "secrets",
        "password",
        "passwd",
        "token",
        "api_key",
        "apikey",
        "private_key",
        "secret_key",
        "access_key",
        "secret_access_key",
        "client_secret",
        "credential",
        "credentials",
        "connection_string",
        "dsn",
    }
)


_SECRET_NAME_WORDS = tuple(tuple(secret.split("_")) for secret in SECRET_CONFIG_NAMES)


def is_secret_config_name(name: str) -> bool:
    """Whether a normalized set/key looks like it names a secret."""
    for part in name.split("."):
        words = tuple(part.split("_"))
        for secret in _SECRET_NAME_WORDS:
            for start in range(len(words) - len(secret) + 1):
                end = start + len(secret)
                if words[start:end] == secret and (start > 0 or end == len(words)):
                    return True
    return False


# A public integer is an optional sign and ASCII digits, so a client's
# ``Number()`` reads the same value; ``coerce_integer`` alone also accepts
# "1_000", "1e3" and non-ASCII digits.
PUBLIC_INTEGER_PATTERN = re.compile(r"^\s*[+-]?[0-9]+\s*$")


def _validate_integer(value: str) -> None:
    if not PUBLIC_INTEGER_PATTERN.match(value):
        raise ValueError(value)
    coerce_integer(value)


def _reject_json_constant(name: str) -> None:
    raise ValueError(f"{name} is not valid JSON.")


def _validate_json(value: str) -> None:
    # Python accepts NaN / Infinity, but a client's JSON.parse does not.
    json.loads(value, parse_constant=_reject_json_constant)


class PublicConfiguration(BaseModel, BaseActivatableModel):
    """A runtime-editable configuration entry served to clients (spec 0034).

    Every row is public: it is returned by an unauthenticated, internet-facing
    API. Secrets MUST NOT be stored here; backend-only values belong in
    ``Configuration``. Read values in-process through ``apps.core.services``.
    """

    class ValueType(models.TextChoices):
        """How clients interpret ``config_value``; storage is always text."""

        STRING = "string", "String"
        INTEGER = "integer", "Integer"
        BOOLEAN = "boolean", "Boolean"
        JSON = "json", "JSON"

    # Parsers that a value of each non-string type must pass.
    VALUE_PARSERS = {
        ValueType.INTEGER: _validate_integer,
        ValueType.BOOLEAN: parse_config_bool,
        ValueType.JSON: _validate_json,
    }

    config_set = models.CharField(max_length=100)
    config_key = models.CharField(max_length=255)
    config_value = models.TextField(blank=True, help_text=PUBLIC_CONFIGURATION_WARNING)
    value_type = models.CharField(
        max_length=16,
        choices=ValueType.choices,
        default=ValueType.STRING,
        help_text="How clients interpret the value. It must parse as this type.",
    )
    description = models.TextField(
        null=True,
        blank=True,
        help_text=(
            "Admin-only note; not returned by the API, but write it as if it "
            "could be read by anyone."
        ),
    )

    class Meta:
        """Meta options."""

        ordering = ("config_set", "config_key")
        constraints = [
            models.UniqueConstraint(
                fields=("config_set", "config_key"),
                name="core_publicconfiguration_unique_set_key",
            ),
        ]
        indexes = [
            models.Index(fields=("config_set",), name="core_public_config_set_idx"),
        ]
        verbose_name = "Public Configuration"
        verbose_name_plural = "Public Configurations"

    def __str__(self):
        return f"{self.config_set}.{self.config_key}"

    def clean(self):
        """Vet the set and key, type-check the value, and reject a pair held in Configuration."""
        super().clean()
        errors = clean_config_names(self)
        for field in ("config_set", "config_key"):
            if field not in errors and is_secret_config_name(getattr(self, field)):
                errors[field] = (
                    "This name looks like a secret. Public configuration is visible "
                    "to internet clients; keep secrets in environment variables."
                )

        parse = self.VALUE_PARSERS.get(self.value_type)
        if parse is not None:
            try:
                parse(self.config_value or "")
            except (ValidationError, ValueError):
                errors["value_type"] = (
                    f"The value does not parse as {self.get_value_type_display()}."
                )

        check_other_config_store(self, Configuration, errors)
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
