"""Organization models."""

import re

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseActivatableModel, BaseExtendableModel, BaseModel

CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")


class OrganizationType(models.TextChoices):
    """Fixed set of organization types relevant to courts."""

    SUPREME_COURT = "supreme_court", "Supreme Court"
    HIGH_COURT = "high_court", "High Court"
    DISTRICT_COURT = "district_court", "District Court"
    SESSION_COURT = "session_court", "Session Court"
    MAGISTRATE_COURT = "magistrate_court", "Magistrate Court"


class Organization(BaseExtendableModel, BaseModel, BaseActivatableModel):
    """A judicial organization in a parent-child hierarchy."""

    code = models.CharField(max_length=50, unique=True)
    organization_type = models.CharField(max_length=50, choices=OrganizationType.choices)
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )

    # TODO(0007-location): spec/0007-location.md (Location module) is not yet
    # implemented in this codebase. Once that app lands, add:
    #   jurisdictions = models.ManyToManyField(
    #       "locations.Location", related_name="organizations"
    #   )

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)

    def clean(self):
        """Validate code format and parent hierarchy constraints."""
        super().clean()
        if self.code and not CODE_PATTERN.match(self.code):
            raise ValidationError({"code": "code must be uppercase snake_case (A-Z, 0-9, _)."})
        if self.parent_id and self.parent_id == self.id:
            raise ValidationError({"parent": "An organization cannot be its own parent."})
        if self.parent_id:
            ancestor = self.parent
            while ancestor is not None:
                if ancestor.id == self.id:
                    raise ValidationError({"parent": "Circular parent chain detected."})
                ancestor = ancestor.parent

    def is_root(self):
        """Return True when this organization has no parent."""
        return self.parent_id is None

    def get_ancestors(self):
        """Return ordered list of ancestors from root to immediate parent."""
        ancestors = []
        node = self.parent
        while node is not None:
            ancestors.insert(0, node)
            node = node.parent
        return ancestors

    def get_descendants(self):
        """Return all nested children recursively.

        TODO: one query per descendant (N+1). Fine for now (no API endpoint
        uses it, subtrees are small). If that changes, switch to a recursive
        SQL CTE / materialized-path column, or django-mptt / django-treebeard
        if tree operations become a heavily-used feature in general.
        """
        descendants = []
        for child in self.children.all():
            descendants.append(child)
            descendants.extend(child.get_descendants())
        return descendants

    def get_full_name(self):
        """Concatenate ancestor names and this organization's name."""
        names = [ancestor.name for ancestor in self.get_ancestors()]
        names.append(self.name)
        return " / ".join(names)

    def __str__(self):
        return self.code
