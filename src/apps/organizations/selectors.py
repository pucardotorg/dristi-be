"""Every court-access read other modules make (spec 0029 #6).

Each selector counts only active assignments of active users at active
organizations, through active roles, and only registered action codes. None
special-cases superusers: Django groups, ``is_staff`` and ``is_superuser``
allow no court action (#3.2).

A **grant** is the unit computed here: ``(action, organization_id, scope)``,
after expanding roles and applying the level rule (#5.4): an assignment at a
courtroom applies the role's courtroom actions there and its establishment
actions at the courtroom's establishment.
"""

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Prefetch, Q

from . import court_actions
from .enums import CourtLevel
from .models import CourtRoleAction, Organization, RoleAssignment

# Attribute holding a user's memoised grants. It lives on the user object of
# one request, so nothing outlives the request (#8.2).
_CACHE_ATTR = "_court_grants_cache"


@dataclass(frozen=True)
class Grant:
    """One action a user may take at one organization, with its scope (None: everything)."""

    action: str
    organization_id: str
    scope: dict | None
    role_id: str


def _is_actor(user):
    """Whether ``user`` is an authenticated, active account."""
    return bool(user is not None and user.is_authenticated and user.is_active)


def scope_matches(scope, process_type=None, channel=None):
    """Whether one scope row covers a process (#5.5).

    ``None`` covers everything; a missing axis covers every code on it. An
    argument left ``None`` does not filter that axis.
    """
    if scope is None:
        return True
    if process_type is not None and "process_types" in scope:
        if process_type not in scope["process_types"]:
            return False
    if channel is not None and "channels" in scope:
        if channel not in scope["channels"]:
            return False
    return True


def _active_assignments():
    """Active assignments that can grant anything, with what the grant needs loaded."""
    return (
        RoleAssignment.objects.filter(
            is_active=True,
            user__is_active=True,
            organization__is_active=True,
            organization__court_level__isnull=False,
            role__is_active=True,
        )
        .select_related("organization", "organization__parent", "role")
        .prefetch_related(
            Prefetch(
                "role__actions", queryset=CourtRoleAction.objects.only("action", "scope", "role_id")
            )
        )
    )


def _grants_for_assignment(assignment):
    """Expand one assignment into its grants, applying the level rule (#5.4)."""
    organization = assignment.organization
    role = assignment.role
    if organization.court_level == CourtLevel.ESTABLISHMENT:
        establishment = organization
    else:
        establishment = organization.parent
        if (
            establishment is None
            or not establishment.is_active
            or establishment.court_level != CourtLevel.ESTABLISHMENT
        ):
            establishment = None
    if role.establishment_id and (
        establishment is None or role.establishment_id != establishment.pk
    ):
        return []

    grants = []
    for row in role.actions.all():
        action = court_actions.get(row.action)
        if action is None:
            continue  # removed without a data migration (W004): ignored
        if action.is_establishment:
            if establishment is None:
                continue
            target = establishment.pk
        else:
            if organization.court_level != CourtLevel.COURTROOM:
                continue  # an establishment has no courtroom to apply it to
            target = organization.pk
        scope = row.scope if action.scoped else None
        grants.append(Grant(action.code, str(target), scope, str(role.pk)))
    return grants


def grants_of(user):
    """Return every grant ``user`` holds, memoised on the user object for the request."""
    if not _is_actor(user):
        return []
    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached
    grants = []
    for assignment in _active_assignments().filter(user_id=user.pk):
        grants.extend(_grants_for_assignment(assignment))
    setattr(user, _CACHE_ATTR, grants)
    return grants


def clear_cache(user):
    """Forget ``user``'s memoised grants (after their access changed within one request)."""
    if user is not None and hasattr(user, _CACHE_ATTR):
        delattr(user, _CACHE_ATTR)


def can(user, action, organization_id, *, process_type=None, channel=None):
    """Whether ``user`` may take ``action`` at the organization.

    ``process_type`` and ``channel`` filter a scoped action; on any other
    action they are ignored.
    """
    action = court_actions.resolve(action)
    if organization_id is None:
        return False
    organization_id = str(organization_id)
    for grant in grants_of(user):
        if grant.action != action.code or grant.organization_id != organization_id:
            continue
        if not action.scoped or scope_matches(grant.scope, process_type, channel):
            return True
    return False


def actions_of(user, organization_id):
    """Return the action codes ``user`` is allowed at the organization (for ``allowed_actions``)."""
    if organization_id is None:
        return frozenset()
    organization_id = str(organization_id)
    return frozenset(
        grant.action for grant in grants_of(user) if grant.organization_id == organization_id
    )


def establishment_of(organization_id):
    """Return the organization's establishment (itself, or a courtroom's parent), or None."""
    if organization_id is None:
        return None
    organization = Organization.objects.select_related("parent").filter(pk=organization_id).first()
    if organization is None:
        return None
    if organization.court_level == CourtLevel.ESTABLISHMENT:
        return organization
    if organization.court_level == CourtLevel.COURTROOM:
        parent = organization.parent
        if parent is not None and parent.court_level == CourtLevel.ESTABLISHMENT:
            return parent
    return None


def action_holders(organization_id, action, *, process_type=None, channel=None):
    """Return the active users allowed ``action`` at the organization.

    Candidates are selected in the database: assignments of roles holding the
    action at the organization or, for an establishment action, at any of its
    courtrooms. Scope is filtered in Python, since a court has few holders.
    """
    action = court_actions.resolve(action)
    user_model = get_user_model()
    organization = Organization.objects.filter(
        pk=organization_id, is_active=True, court_level__isnull=False
    ).first()
    if organization is None:
        return user_model.objects.none()

    if action.is_establishment:
        if organization.court_level != CourtLevel.ESTABLISHMENT:
            return user_model.objects.none()
        where = Q(role__assignments__organization_id=organization.pk) | Q(
            role__assignments__organization__parent_id=organization.pk,
            role__assignments__organization__court_level=CourtLevel.COURTROOM,
        )
        establishment_id = organization.pk
    else:
        if organization.court_level != CourtLevel.COURTROOM:
            return user_model.objects.none()
        parent = organization.parent
        if parent is None or not parent.is_active or parent.court_level != CourtLevel.ESTABLISHMENT:
            # A courtroom whose establishment is gone grants nothing there either.
            establishment_id = None
        else:
            establishment_id = parent.pk
        where = Q(role__assignments__organization_id=organization.pk)

    rows = CourtRoleAction.objects.filter(
        where,
        Q(role__establishment__isnull=True) | Q(role__establishment_id=establishment_id),
        action=action.code,
        role__is_active=True,
        role__assignments__is_active=True,
        role__assignments__user__is_active=True,
        role__assignments__organization__is_active=True,
    ).values_list("role__assignments__user_id", "scope")

    user_ids = {
        user_id
        for user_id, scope in rows
        if not action.scoped or scope_matches(scope, process_type, channel)
    }
    return user_model.objects.filter(pk__in=user_ids, is_active=True).order_by("mobile_number")


def establishments_of(user, actions=None):
    """Return the establishments where ``user`` is allowed any establishment action.

    With ``actions`` (constants), only those actions count.
    """
    codes = None
    if actions is not None:
        codes = {court_actions.resolve(action).code for action in actions}
    ids = {
        grant.organization_id
        for grant in grants_of(user)
        if court_actions.get(grant.action).is_establishment
        and (codes is None or grant.action in codes)
    }
    return Organization.objects.filter(pk__in=ids).order_by("name")


def courtrooms_of(user):
    """Return the active courtrooms on ``user``'s list (``REG-35``), by name."""
    if not _is_actor(user):
        return Organization.objects.none()
    return (
        Organization.objects.filter(
            is_active=True,
            court_level=CourtLevel.COURTROOM,
            staff_assignments__user_id=user.pk,
            staff_assignments__is_active=True,
        )
        .select_related("parent")
        .distinct()
        .order_by("name")
    )


def staff_of_courtroom(courtroom_id):
    """Return the active users with the courtroom on their list."""
    user_model = get_user_model()
    return (
        user_model.objects.filter(
            is_active=True,
            courtroom_assignments__courtroom_id=courtroom_id,
            courtroom_assignments__is_active=True,
            courtroom_assignments__courtroom__is_active=True,
            courtroom_assignments__courtroom__court_level=CourtLevel.COURTROOM,
        )
        .distinct()
        .order_by("mobile_number")
    )


def courtrooms(establishment_id):
    """Return the establishment's active courtrooms, by name (the choice in ``SCR-16``)."""
    return Organization.objects.filter(
        parent_id=establishment_id,
        parent__court_level=CourtLevel.ESTABLISHMENT,
        is_active=True,
        court_level=CourtLevel.COURTROOM,
    ).order_by("name")


def is_court_reader(user, establishment_id, courtroom_id=None):
    """Whether ``user`` reads a case at the court (``RLE-06``, #6.1).

    With no courtroom yet: allowed any establishment action at the
    establishment. With a courtroom: on that courtroom's list.
    """
    if not _is_actor(user):
        return False
    if courtroom_id is not None:
        return staff_of_courtroom(courtroom_id).filter(pk=user.pk).exists()
    if establishment_id is None:
        return False
    establishment_id = str(establishment_id)
    return any(
        grant.organization_id == establishment_id
        and court_actions.get(grant.action).is_establishment
        for grant in grants_of(user)
    )


def _action_entries(grants):
    """Render grants at one court as codes, or ``{action, scopes}`` for a scoped action."""
    scopes = {}
    for grant in grants:
        scopes.setdefault(grant.action, [])
        if court_actions.get(grant.action).scoped:
            scope = grant.scope or {}
            if scope not in scopes[grant.action]:
                scopes[grant.action].append(scope)
    entries = []
    for code in sorted(scopes):
        if court_actions.get(code).scoped:
            entries.append({"action": code, "scopes": scopes[code]})
        else:
            entries.append(code)
    return entries


def court_access_summary(user):
    """The caller's courts and what they may do there, for ``GET /court-roles/me/`` (#9.2).

    An establishment is listed when the caller is allowed an action there or
    has one of its courtrooms on their list; only listed courtrooms are shown.
    Actions are effective: an establishment action held through a courtroom
    role is listed on the establishment.
    """
    if not _is_actor(user):
        return {"establishments": []}
    grants = grants_of(user)
    by_organization = {}
    for grant in grants:
        by_organization.setdefault(grant.organization_id, []).append(grant)

    listed = list(courtrooms_of(user))
    roles_by_courtroom = {}
    for assignment in (
        RoleAssignment.objects.filter(
            user_id=user.pk,
            is_active=True,
            role__is_active=True,
            organization_id__in=[courtroom.pk for courtroom in listed],
        )
        .select_related("role")
        .order_by("role__name")
    ):
        roles_by_courtroom.setdefault(str(assignment.organization_id), []).append(
            {"code": assignment.role.code, "name": assignment.role.name}
        )

    establishment_ids = {
        grant.organization_id
        for grant in grants
        if court_actions.get(grant.action).is_establishment
    }
    establishment_ids |= {
        str(courtroom.parent_id)
        for courtroom in listed
        if courtroom.parent is not None
        and courtroom.parent.is_active
        and courtroom.parent.court_level == CourtLevel.ESTABLISHMENT
    }
    establishments = Organization.objects.filter(pk__in=establishment_ids).order_by("name")

    result = []
    for establishment in establishments:
        key = str(establishment.pk)
        result.append(
            {
                "id": establishment.pk,
                "name": establishment.name,
                "actions": _action_entries(by_organization.get(key, [])),
                "courtrooms": [
                    {
                        "id": courtroom.pk,
                        "name": courtroom.name,
                        "roles": roles_by_courtroom.get(str(courtroom.pk), []),
                        "actions": _action_entries(by_organization.get(str(courtroom.pk), [])),
                    }
                    for courtroom in listed
                    if str(courtroom.parent_id) == key
                ],
            }
        )
    return {"establishments": result}
