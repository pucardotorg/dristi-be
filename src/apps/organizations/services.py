"""Assigning, revoking and editing court roles (spec 0029 #8).

Admin and seeding-time tools call these; nothing writes the role and
assignment models directly. Each runs in one transaction, records ``actor``
as ``updated_by`` and in history, and sends ``court_access_changed`` after
commit. Roles and assignments are deactivated, never deleted.
"""

import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from . import court_actions, selectors
from .enums import CourtLevel
from .models import (
    CourtRole,
    CourtRoleAction,
    CourtroomAssignment,
    RoleAssignment,
    assignment_problems,
    citizen_problem,
    clean_scope,
    courtroom_action_codes,
    establishment_id_of,
)
from .signals import send_after_commit


def _stamp(instance, actor, *, creating=False):
    """Record ``actor`` as the audit and history user of the change."""
    if creating:
        instance.created_by = actor
    instance.updated_by = actor
    instance._history_user = actor


def _has_establishment_action(codes):
    """Whether any of ``codes`` is a registered establishment action."""
    return any(
        (action := court_actions.get(code)) is not None and action.is_establishment
        for code in codes
    )


def _affected_organizations(organization, codes):
    """The organization, plus a courtroom's establishment when establishment actions are involved."""
    ids = {organization.pk}
    if organization.court_level == CourtLevel.COURTROOM and _has_establishment_action(codes):
        ids.add(establishment_id_of(organization))
    return ids


def _save_or_adopt(assignment, active):
    """Save ``assignment``; when a concurrent call saved the same one first, return that row.

    Two simultaneous assigns both pass the "already active?" check, and the
    loser then fails the active-row unique constraint (``IntegrityError``, or
    ``ValidationError`` from ``full_clean`` when the winner committed first).
    The requested state already exists, so the call still succeeds.
    Returns ``(row, saved)``; ``saved`` is False when the other call's row is returned.
    """
    try:
        with transaction.atomic():
            assignment.full_clean()
            assignment.save()
    except (IntegrityError, ValidationError):
        winner = active.first()
        if winner is None:
            raise
        return winner, False
    return assignment, True


def _role_codes(role):
    """The action codes a role holds."""
    return set(role.actions.values_list("action", flat=True))


# -- courtroom list (REG-35) ---------------------------------------------------


@transaction.atomic
def assign_courtroom(user, courtroom, *, actor):
    """Put ``courtroom`` on ``user``'s list; reactivate a removed entry. Idempotent."""
    assignment = CourtroomAssignment.objects.filter(
        user=user, courtroom=courtroom, is_active=True
    ).first()
    if assignment is not None:
        return assignment
    problem = citizen_problem(user)
    if problem:
        raise ValidationError(problem)
    assignment = (
        CourtroomAssignment.objects.filter(user=user, courtroom=courtroom, is_active=False)
        .order_by("-updated_at")
        .first()
    )
    creating = assignment is None
    if creating:
        assignment = CourtroomAssignment(user=user, courtroom=courtroom)
    assignment.is_active = True
    _stamp(assignment, actor, creating=creating)
    active = CourtroomAssignment.objects.filter(user=user, courtroom=courtroom, is_active=True)
    assignment, saved = _save_or_adopt(assignment, active)
    selectors.clear_cache(user)
    if saved:
        send_after_commit([courtroom.pk])
    return assignment


@transaction.atomic
def remove_courtroom(user, courtroom, *, actor):
    """Take ``courtroom`` off ``user``'s list, and revoke their roles there."""
    assignments = list(
        CourtroomAssignment.objects.select_for_update().filter(
            user=user, courtroom=courtroom, is_active=True
        )
    )
    revoked = list(
        RoleAssignment.objects.select_for_update()
        .select_related("role")
        .filter(user=user, organization=courtroom, is_active=True)
    )
    if not assignments and not revoked:
        return
    organization_ids = {courtroom.pk}
    for role_assignment in revoked:
        role_assignment.is_active = False
        _stamp(role_assignment, actor)
        role_assignment.save()
        organization_ids |= _affected_organizations(courtroom, _role_codes(role_assignment.role))
    for assignment in assignments:
        assignment.is_active = False
        _stamp(assignment, actor)
        assignment.save()
    selectors.clear_cache(user)
    send_after_commit(organization_ids)


# -- role assignments ----------------------------------------------------------


@transaction.atomic
def assign_role(user, organization, role, *, actor):
    """Give ``user`` the role at the organization; reactivate a revoked one. Idempotent.

    Raises ``ValidationError`` when the assignment breaks the rules of #5.4.
    """
    assignment = RoleAssignment.objects.filter(
        user=user, organization=organization, role=role, is_active=True
    ).first()
    if assignment is not None:
        return assignment
    problems = assignment_problems(user, organization, role)
    if problems:
        raise ValidationError(problems)
    assignment = (
        RoleAssignment.objects.filter(
            user=user, organization=organization, role=role, is_active=False
        )
        .order_by("-updated_at")
        .first()
    )
    creating = assignment is None
    if creating:
        assignment = RoleAssignment(user=user, organization=organization, role=role)
    assignment.is_active = True
    _stamp(assignment, actor, creating=creating)
    active = RoleAssignment.objects.filter(
        user=user, organization=organization, role=role, is_active=True
    )
    assignment, saved = _save_or_adopt(assignment, active)
    selectors.clear_cache(user)
    if saved:
        codes = _role_codes(role)
        send_after_commit(_affected_organizations(organization, codes), codes)
    return assignment


@transaction.atomic
def revoke_role(user, organization, role, *, actor):
    """Take the role at the organization away from ``user``. A no-op when not held."""
    assignments = list(
        RoleAssignment.objects.select_for_update().filter(
            user=user, organization=organization, role=role, is_active=True
        )
    )
    if not assignments:
        return
    for assignment in assignments:
        assignment.is_active = False
        _stamp(assignment, actor)
        assignment.save()
    selectors.clear_cache(user)
    codes = _role_codes(role)
    send_after_commit(_affected_organizations(organization, codes), codes)


# -- roles ---------------------------------------------------------------------


def _scope_key(scope):
    """A hashable form of a (normalized) scope."""
    return None if scope is None else json.dumps(scope, sort_keys=True)


def _entry(entry):
    """Return ``(code, scope)`` from an entry: a pair, a dict or an action constant."""
    if isinstance(entry, court_actions.CourtAction):
        return entry.code, None
    if isinstance(entry, dict):
        action = entry.get("action")
        scope = entry.get("scope")
    else:
        action, scope = entry
    code = action.code if isinstance(action, court_actions.CourtAction) else action
    return code, scope


def clean_role_actions(role, entries):
    """Validate ``entries`` for ``role``; return the normalized ``[(code, scope)]``.

    Raises ``ValidationError`` for an undeclared action, a bad scope, an
    unscoped action listed twice, the same scope listed twice, or a courtroom
    action in a role assigned at an establishment.
    """
    cleaned, seen, errors = [], set(), []
    for entry in entries:
        code, scope = _entry(entry)
        action = court_actions.get(code)
        if action is None:
            errors.append(f"{code!r} is not a declared court action.")
            continue
        try:
            scope = clean_scope(action, scope)
        except ValidationError as exc:
            errors.extend(f"{code}: {message}" for message in exc.messages)
            continue
        key = (code, _scope_key(scope))
        if key in seen:
            errors.append(
                f"{code} is listed twice with the same scope."
                if action.scoped
                else f"{code} is listed twice."
            )
            continue
        seen.add(key)
        cleaned.append((code, scope))
    if role is not None and role.pk is not None:
        courtroom_codes = courtroom_action_codes(code for code, _ in cleaned)
        if (
            courtroom_codes
            and RoleAssignment.objects.filter(
                role_id=role.pk,
                is_active=True,
                organization__court_level=CourtLevel.ESTABLISHMENT,
            ).exists()
        ):
            errors.append(
                "This role is assigned at an establishment, which has no courtroom, so it cannot "
                f"hold courtroom action(s) {', '.join(courtroom_codes)}."
            )
    if errors:
        raise ValidationError(errors)
    return cleaned


def _organizations_holding(role, codes):
    """Every organization where ``role`` is assigned, with courtroom establishments if needed."""
    ids = set()
    for assignment in RoleAssignment.objects.filter(role=role, is_active=True).select_related(
        "organization"
    ):
        ids |= _affected_organizations(assignment.organization, codes)
    return ids


@transaction.atomic
def set_role_actions(role, entries, *, actor):
    """Replace the role's actions with ``entries`` (see ``clean_role_actions``).

    Unchanged rows are kept, so history records only what changed. Returns
    the set of codes added or removed.
    """
    wanted = clean_role_actions(role, entries)
    wanted_keys = {(code, _scope_key(scope)): scope for code, scope in wanted}
    existing = {
        (row.action, _scope_key(row.scope)): row
        for row in CourtRoleAction.objects.select_for_update().filter(role=role)
    }
    changed = set()
    for key, row in existing.items():
        if key not in wanted_keys:
            row._history_user = actor
            row.delete()
            changed.add(row.action)
    for key, scope in wanted_keys.items():
        if key in existing:
            continue
        row = CourtRoleAction(role=role, action=key[0], scope=scope)
        _stamp(row, actor, creating=True)
        row.save()
        changed.add(key[0])
    if changed:
        send_after_commit(_organizations_holding(role, changed), changed)
    return changed


def validate_role_fields(role):
    """Refuse moving a role to an establishment it is assigned outside of."""
    if not role.establishment_id or role._state.adding:
        return
    outside = {
        assignment.organization.code
        for assignment in RoleAssignment.objects.filter(role=role, is_active=True).select_related(
            "organization"
        )
        if establishment_id_of(assignment.organization) != role.establishment_id
    }
    if outside:
        raise ValidationError(
            {
                "establishment": (
                    f"The role is assigned outside this establishment, at {', '.join(sorted(outside))}."
                )
            }
        )


@transaction.atomic
def save_role(role, *, actor):
    """Create or update a role's own fields (code, name, establishment, active).

    Refuses moving a role to an establishment it is assigned outside of.
    Activating or deactivating a role, or moving it, notifies every
    organization where it is assigned.
    """
    creating = role._state.adding
    previous = None if creating else CourtRole.objects.filter(pk=role.pk).first()
    role.full_clean()
    validate_role_fields(role)
    _stamp(role, actor, creating=creating)
    role.save()
    if previous is not None and (
        previous.is_active != role.is_active or previous.establishment_id != role.establishment_id
    ):
        codes = _role_codes(role)
        send_after_commit(_organizations_holding(role, codes), codes)
    return role
