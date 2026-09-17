"""Location models providing a self-referential administrative hierarchy."""

import re

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseActivatableModel, BaseExtendableModel, BaseModel

CODE_RE = re.compile(r"^[A-Z0-9_]+$")

FULL_NAME_SEPARATOR = " / "


class Location(BaseExtendableModel, BaseModel, BaseActivatableModel):
    """An administrative area in a hierarchy of countries, states and districts."""

    class LocationType(models.TextChoices):
        """Supported administrative levels."""

        COUNTRY = "country", "Country"
        STATE = "state", "State"
        DISTRICT = "district", "District"

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=100, blank=True)
    location_type = models.CharField(
        max_length=50,
        choices=LocationType.choices,
        db_index=True,
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )

    class Meta:
        """Meta options."""

        ordering = ("code",)
        verbose_name = "Location"
        verbose_name_plural = "Locations"

    def __str__(self):
        """Return a readable label for admin and logs."""
        return f"{self.name} ({self.code})"

    def clean(self):
        """Validate the code format, location type and parent hierarchy."""
        super().clean()
        if not self.code or not CODE_RE.match(self.code):
            raise ValidationError(
                {"code": "Must be uppercase snake_case matching ^[A-Z0-9_]+$ (e.g. IN_BR_PATNA)."}
            )
        if self.location_type not in self.LocationType.values:
            raise ValidationError(
                {"location_type": (f"Must be one of: {', '.join(self.LocationType.values)}.")}
            )
        self._validate_parent()

    def _validate_parent(self):
        """Reject self-parenting and circular parent chains."""
        if self.parent_id is None:
            return
        if self.parent_id == self.pk:
            raise ValidationError({"parent": "A location cannot be its own parent."})

        seen = {self.pk}
        ancestor = self.parent
        while ancestor is not None:
            if ancestor.pk == self.pk:
                raise ValidationError({"parent": "Circular parent chain is not allowed."})
            if ancestor.pk in seen:
                break
            seen.add(ancestor.pk)
            ancestor = ancestor.parent

    def is_root(self):
        """Return True when this location has no parent."""
        return self.parent_id is None

    def get_ancestors(self):
        """Return ancestors ordered from the root down to the immediate parent."""
        ancestors = []
        seen = {self.pk}
        ancestor = self.parent
        while ancestor is not None and ancestor.pk not in seen:
            ancestors.append(ancestor)
            seen.add(ancestor.pk)
            ancestor = ancestor.parent
        ancestors.reverse()
        return ancestors

    def get_descendants(self):
        """Return every nested child, breadth-first."""
        descendants = []
        seen = {self.pk}
        frontier = [self]
        while frontier:
            children = Location.objects.filter(
                parent__in=[node.pk for node in frontier]
            ).select_related("parent")
            frontier = []
            for child in children:
                if child.pk in seen:
                    continue
                seen.add(child.pk)
                descendants.append(child)
                frontier.append(child)
        return descendants

    def get_full_name(self):
        """Return the ancestor chain and this name, e.g. "India / Bihar / Patna"."""
        names = [ancestor.name for ancestor in self.get_ancestors()]
        names.append(self.name)
        return FULL_NAME_SEPARATOR.join(names)
