"""Organization models, and court roles and assignments (spec 0029)."""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import (
    ActivatableQuerySet,
    BaseActivatableModel,
    BaseAuditableModel,
    BaseExtendableModel,
    BaseModel,
)

from . import court_actions
from .enums import CourtLevel

CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")
# Scope keys a process action's scope may restrict (spec 0029 #5.5, RLE-09).
SCOPE_AXES = ("process_types", "channels")


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

    jurisdictions = models.ManyToManyField(
        "locations.Location", related_name="organizations", blank=True
    )
    # Where the organization sits in the court hierarchy (spec 0029 #2); null
    # on any organization that holds no court access.
    court_level = models.CharField(
        max_length=20, choices=CourtLevel.choices, null=True, blank=True, default=None
    )

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
        self._clean_court_level()

    def _clean_court_level(self):
        """Validate the court hierarchy (spec 0029 #2)."""
        if self.court_level == "":
            self.court_level = None
        if self.court_level == CourtLevel.COURTROOM:
            if self.parent is None or self.parent.court_level != CourtLevel.ESTABLISHMENT:
                raise ValidationError(
                    {"court_level": "A courtroom must have a court establishment as its parent."}
                )
        elif self.court_level == CourtLevel.ESTABLISHMENT:
            if any(ancestor.court_level for ancestor in self.get_ancestors()):
                raise ValidationError(
                    {
                        "court_level": (
                            "A court establishment cannot sit under another establishment "
                            "or a courtroom."
                        )
                    }
                )
        if self._state.adding:
            return
        stored = Organization.objects.filter(pk=self.pk).values_list("court_level", flat=True)
        stored_level = stored.first()
        if stored_level == self.court_level:
            return
        in_use = (
            RoleAssignment.objects.filter(organization_id=self.pk, is_active=True).exists()
            or CourtroomAssignment.objects.filter(courtroom_id=self.pk, is_active=True).exists()
        )
        if in_use:
            raise ValidationError(
                {"court_level": "The court level cannot change while staff are assigned here."}
            )

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


# ---------------------------------------------------------------------------
# Court roles and assignments (spec 0029 #4, #5)
# ---------------------------------------------------------------------------


def establishment_id_of(organization):
    """Return the id of ``organization``'s establishment: itself, or a courtroom's parent."""
    if organization is None:
        return None
    if organization.court_level == CourtLevel.ESTABLISHMENT:
        return organization.pk
    if organization.court_level == CourtLevel.COURTROOM:
        return organization.parent_id
    return None


def clean_scope(action, scope):
    """Return ``scope`` normalized for ``action``; raise ValidationError if it is invalid (#5.5).

    ``None`` (and ``{}``) cover every process type on every channel. A missing
    axis covers every code on it; a list covers only those codes. An empty
    list is refused: leave the key out instead.
    """
    if scope in (None, {}):
        return None
    if not action.scoped:
        raise ValidationError(
            {"scope": f"{action.code} is not a scoped action; leave scope empty."}
        )
    if not isinstance(scope, dict):
        raise ValidationError({"scope": "Scope must be an object of process_types and channels."})
    unknown = sorted(set(scope) - set(SCOPE_AXES))
    if unknown:
        raise ValidationError({"scope": f"Unknown scope key(s): {', '.join(unknown)}."})
    cleaned = {}
    for axis in SCOPE_AXES:
        if axis not in scope:
            continue
        codes = scope[axis]
        if not isinstance(codes, list) or not codes:
            raise ValidationError(
                {"scope": f"{axis} must be a non-empty list; leave it out to cover every code."}
            )
        if not all(isinstance(code, str) and CODE_PATTERN.match(code) for code in codes):
            raise ValidationError({"scope": f"{axis} must be uppercase codes (A-Z, 0-9, _)."})
        cleaned[axis] = sorted(set(codes))
    return cleaned


class CourtRoleManager(models.Manager.from_queryset(ActivatableQuerySet)):
    """Looks roles up by their natural key for seeding (spec 0025)."""

    def get_by_natural_key(self, code, establishment_code=None):
        """Return the active role ``code``, deployment-wide or of ``establishment_code``.

        Written ``CODE`` or ``CODE.ESTABLISHMENT_CODE`` in a seed file.
        """
        if establishment_code:
            return self.get(is_active=True, code=code, establishment__code=establishment_code)
        return self.get(is_active=True, code=code, establishment__isnull=True)


class CourtRole(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """A named bundle of court actions: a staff title such as Magistrate (spec 0029 #4, #5.1).

    Data, so each court decides what its titles allow. Code never reads a
    role (``RLE-08``); it checks actions.
    """

    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    # Null: usable anywhere in the deployment. Set: only at that establishment
    # and its courtrooms (a court whose titles differ, or a one-person exception).
    establishment = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="court_roles",
    )

    objects = CourtRoleManager()

    class Meta:
        """Meta options."""

        ordering = ("code",)
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_active=True, establishment__isnull=True),
                name="organizations_courtrole_active_code_unique",
                violation_error_message="An active deployment-wide role with this code exists.",
            ),
            models.UniqueConstraint(
                fields=["code", "establishment"],
                condition=Q(is_active=True, establishment__isnull=False),
                name="organizations_courtrole_active_code_establishment_unique",
                violation_error_message="An active role with this code exists at this establishment.",
            ),
        ]

    def clean(self):
        """Validate the code and the establishment's level."""
        super().clean()
        if self.code and not CODE_PATTERN.match(self.code):
            raise ValidationError({"code": "code must be uppercase snake_case (A-Z, 0-9, _)."})
        if self.establishment_id and self.establishment.court_level != CourtLevel.ESTABLISHMENT:
            raise ValidationError({"establishment": "Must be a court establishment."})

    def natural_key(self):
        """Return ``(code, establishment code)`` for seeding."""
        return (self.code, self.establishment.code if self.establishment_id else None)

    def __str__(self):
        if self.establishment_id:
            return f"{self.name} ({self.code} @ {self.establishment.code})"
        return f"{self.name} ({self.code})"


class CourtRoleAction(BaseModel, BaseAuditableModel):
    """One action a role holds, with its scope for a process action (spec 0029 #5.2)."""

    role = models.ForeignKey(CourtRole, on_delete=models.CASCADE, related_name="actions")
    # A registered action code (#3.1): a plain string, so a new action needs no migration.
    action = models.CharField(max_length=100)
    scope = models.JSONField(null=True, blank=True, default=None)

    class Meta:
        """Meta options."""

        ordering = ("action", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=["role", "action"],
                condition=Q(scope__isnull=True),
                name="organizations_courtroleaction_unscoped_unique",
                violation_error_message="The role already holds this action.",
            ),
        ]
        indexes = [models.Index(fields=["action"])]

    def clean(self):
        """Validate the action against the registry, its scope, and the role's assignments."""
        super().clean()
        action = court_actions.get(self.action)
        if action is None:
            raise ValidationError({"action": f"{self.action!r} is not a declared court action."})
        self.scope = clean_scope(action, self.scope)
        if self.role_id is None:
            return
        if self.scope is not None:
            others = CourtRoleAction.objects.filter(role_id=self.role_id, action=self.action)
            if any(row.scope == self.scope for row in others.exclude(pk=self.pk)):
                raise ValidationError(
                    {"scope": "The role already holds this action with this scope."}
                )
        if not action.is_establishment and role_assigned_at_establishment(self.role_id):
            raise ValidationError(
                {
                    "action": (
                        f"{action.code} is a courtroom action, and this role is assigned at an "
                        "establishment, which has no courtroom to apply it to."
                    )
                }
            )

    def __str__(self):
        return f"{self.action} {self.scope}" if self.scope else self.action


def role_assigned_at_establishment(role_id):
    """Whether the role has an active assignment at an establishment (spec 0029 #5.4)."""
    return RoleAssignment.objects.filter(
        role_id=role_id,
        is_active=True,
        organization__court_level=CourtLevel.ESTABLISHMENT,
    ).exists()


class CourtroomAssignment(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """A courtroom on a staff account's list (spec 0029 #5.3, ``REG-35``).

    Makes the user staff of the courtroom: they read its cases (``RLE-06``)
    and may choose it after login (``REG-36``). It grants no action.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="courtroom_assignments"
    )
    courtroom = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="staff_assignments"
    )

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["user", "courtroom"],
                condition=Q(is_active=True),
                name="organizations_courtroomassignment_active_unique",
                violation_error_message="The user already has this courtroom on their list.",
            ),
        ]
        indexes = [
            models.Index(fields=["courtroom", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]

    def clean(self):
        """Refuse a courtroom that is not an active courtroom."""
        super().clean()
        if not self.is_active or self.courtroom_id is None:
            return
        if self.courtroom.court_level != CourtLevel.COURTROOM:
            raise ValidationError({"courtroom": "Must be a courtroom."})
        if not self.courtroom.is_active:
            raise ValidationError({"courtroom": "The courtroom is not active."})

    def __str__(self):
        return f"{self.user} @ {self.courtroom}"


class RoleAssignment(BaseModel, BaseActivatableModel, BaseAuditableModel):
    """A user holding a role at an establishment or a courtroom (spec 0029 #5.4).

    At a courtroom, the role's courtroom actions apply at that courtroom and
    its establishment actions at the courtroom's establishment.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="role_assignments"
    )
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="role_assignments"
    )
    role = models.ForeignKey(CourtRole, on_delete=models.PROTECT, related_name="assignments")

    class Meta:
        """Meta options."""

        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=["user", "organization", "role"],
                condition=Q(is_active=True),
                name="organizations_roleassignment_active_unique",
                violation_error_message="The user already holds this role here.",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "is_active"]),
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["role", "is_active"]),
        ]

    def clean(self):
        """Validate an active assignment (spec 0029 #5.4)."""
        super().clean()
        if not self.is_active or None in (self.organization_id, self.role_id, self.user_id):
            return
        problems = assignment_problems(self.user_id, self.organization, self.role)
        if problems:
            raise ValidationError(problems)

    def __str__(self):
        return f"{self.user} - {self.role.code} @ {self.organization}"


def assignment_problems(user_id, organization, role):
    """Return why a role cannot be held at ``organization``, as a field -> message dict.

    Shared by ``RoleAssignment.clean``, the services and system check W002.
    """
    if not organization.is_active:
        return {"organization": "The organization is not active."}
    if not organization.court_level:
        return {"organization": "Must be a court establishment or a courtroom."}
    if organization.court_level == CourtLevel.COURTROOM:
        listed = CourtroomAssignment.objects.filter(
            user_id=user_id, courtroom_id=organization.pk, is_active=True
        ).exists()
        if not listed:
            return {
                "organization": (
                    "Put the courtroom on the user's courtroom list before assigning a role there."
                )
            }
    if not role.is_active:
        return {"role": "The role is not active."}
    if role.establishment_id and role.establishment_id != establishment_id_of(organization):
        return {"role": "This role belongs to another establishment."}
    if organization.court_level == CourtLevel.ESTABLISHMENT:
        courtroom_actions = courtroom_action_codes(role.actions.values_list("action", flat=True))
        if courtroom_actions:
            return {
                "role": (
                    "A role assigned at an establishment may hold only establishment actions; "
                    f"this one holds {', '.join(courtroom_actions)}."
                )
            }
    return {}


def courtroom_action_codes(codes):
    """Return the registered courtroom-level codes among ``codes``, sorted."""
    return sorted(
        {
            code
            for code in codes
            if (action := court_actions.get(code)) is not None and not action.is_establishment
        }
    )
