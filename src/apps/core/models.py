"""Shared base model used across the project."""

import copy
import uuid

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models

from .validators import (
    DATA_TYPE_CHOICES,
    coerce_value,
    validate_attribute_name,
    validate_default_value,
)


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
    """Abstract base model with UUID primary key and timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        """Meta options."""

        abstract = True
        ordering = ("-created_at",)


class BaseExtendableModel(BaseModel):
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


class AdditionalAttribute(BaseModel):
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


class ApiVersionChangeLog(BaseExtendableModel, BaseActivatableModel):
    """API version change-log entry that uses BaseExtendableModel."""

    version = models.CharField(max_length=50)
    change_log = models.TextField()

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        verbose_name = "API Version Change Log"
        verbose_name_plural = "API Version Change Logs"
