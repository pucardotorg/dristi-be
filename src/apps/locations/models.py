"""Location models providing a self-referential administrative hierarchy."""

import re

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseActivatableModel, BaseExtendableModel, BaseModel

CODE_RE = re.compile(r"^[A-Z0-9_]+$")
# An RBI IFSC: four-letter bank code, a zero, then six branch characters.
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

FULL_NAME_SEPARATOR = " / "


class Location(BaseExtendableModel, BaseModel, BaseActivatableModel):
    """An area in a hierarchy of countries, states, districts, pincodes and banks."""

    class LocationType(models.TextChoices):
        """Supported administrative levels."""

        COUNTRY = "country", "Country"
        STATE = "state", "State"
        DISTRICT = "district", "District"
        # A postal pincode under its district; seeded from TOML with the
        # `seed` management command (spec 0025).
        PINCODE = "pincode", "Pincode"
        # A bank branch keyed by its IFSC, under its state or district, so the
        # filing form can fill bank details from an IFSC (issue #249).
        BANK = "bank", "Bank"

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
        if self.location_type == self.LocationType.BANK and not IFSC_RE.match(self.code):
            raise ValidationError({"code": "A bank's code must be its IFSC, e.g. SBIN0001234."})
        self._validate_parent()

    def _validate_parent(self):
        """Reject self-parenting, circular chains and anything that breaks a leaf's chain.

        Address forms read a pincode's district and state from its ancestors,
        so a pincode must sit directly under a district; a bank sits under its
        state or district. Pincodes and banks stay leaves, and a location
        holding them keeps a type they may sit under.
        """
        parent_type = self.parent.location_type if self.parent_id is not None else None
        allowed_parents = LEAF_PARENT_TYPES.get(self.location_type)
        if allowed_parents is not None and parent_type not in allowed_parents:
            raise ValidationError({"parent": LEAF_PARENT_MESSAGES[self.location_type]})
        if parent_type in LEAF_TYPES:
            label = self.parent.get_location_type_display().lower()
            raise ValidationError({"parent": f"A {label} cannot have locations under it."})
        if self.pk is not None and not self._state.adding:
            self._validate_type_change()
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

    def _validate_type_change(self):
        """Keep a saved location's type consistent with the locations under it."""
        children = Location.objects.filter(parent_id=self.pk)
        if self.location_type in LEAF_TYPES and children.exists():
            label = self.get_location_type_display().lower()
            raise ValidationError(
                {"location_type": f"A location with locations under it cannot be a {label}."}
            )
        for leaf_type, parent_types in LEAF_PARENT_TYPES.items():
            if (
                self.location_type not in parent_types
                and children.filter(location_type=leaf_type).exists()
            ):
                raise ValidationError({"location_type": LEAF_HOLDER_MESSAGES[leaf_type]})

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


# Leaf types: nothing may sit under them, and each sits only under these types.
LEAF_PARENT_TYPES = {
    Location.LocationType.PINCODE: {Location.LocationType.DISTRICT},
    Location.LocationType.BANK: {Location.LocationType.STATE, Location.LocationType.DISTRICT},
}
LEAF_TYPES = frozenset(LEAF_PARENT_TYPES)
LEAF_PARENT_MESSAGES = {
    Location.LocationType.PINCODE: "A pincode must be under a district.",
    Location.LocationType.BANK: "A bank must be under a state or a district.",
}
LEAF_HOLDER_MESSAGES = {
    Location.LocationType.PINCODE: "A location with pincodes under it must stay a district.",
    Location.LocationType.BANK: "A location with banks under it must stay a state or a district.",
}
