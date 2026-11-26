"""System checks on the court hierarchy, roles and action registry (spec 0029 #9.3).

``E003`` runs always. The rest read the database, so they are tagged
``database`` and run with ``manage.py check --database default``; they are
skipped before migration.
"""

from django.core.checks import Error, Tags, Warning, register
from django.db import DatabaseError

from . import court_actions


@register()
def check_registry(app_configs, **kwargs):
    """E003: an action code declared twice, or not ``<app>.<action>`` lowercase."""
    problems = list(court_actions.problems())
    for action in court_actions.all():
        if not court_actions.CODE_RE.fullmatch(action.code):
            problems.append(f"Court action code {action.code!r} must be <app>.<action>, lowercase.")
    return [Error(problem, id="organizations.E003") for problem in problems]


@register(Tags.database)
def check_court_data(app_configs, databases=None, **kwargs):
    """W001, E001, W002, W003, W004 (run with ``check --database``)."""
    if not databases:
        return []
    try:
        return [
            *_establishments_without_courtrooms(),
            *_courtrooms_with_bad_parent(),
            *_invalid_assignments(),
            *_roles_without_actions(),
            *_undeclared_actions(),
        ]
    except DatabaseError:
        # Not migrated yet: ``migrate`` runs database checks before it creates the tables.
        return []


def _establishments_without_courtrooms():
    from .enums import CourtLevel
    from .models import Organization

    with_courtrooms = Organization.objects.filter(
        is_active=True, court_level=CourtLevel.COURTROOM, parent__isnull=False
    ).values("parent_id")
    establishments = Organization.objects.filter(
        is_active=True, court_level=CourtLevel.ESTABLISHMENT
    ).exclude(pk__in=with_courtrooms)
    return [
        Warning(
            f"Court establishment {org.code} has no active courtroom.",
            hint="Add a courtroom under it: there is no courtroom to choose otherwise (RLE-00).",
            obj=org,
            id="organizations.W001",
        )
        for org in establishments.order_by("code")
    ]


def _courtrooms_with_bad_parent():
    from .enums import CourtLevel
    from .models import Organization

    courtrooms = (
        Organization.objects.filter(is_active=True, court_level=CourtLevel.COURTROOM)
        .exclude(parent__is_active=True, parent__court_level=CourtLevel.ESTABLISHMENT)
        .order_by("code")
    )
    return [
        Error(
            f"Courtroom {org.code}'s parent is not an active court establishment.",
            obj=org,
            id="organizations.E001",
        )
        for org in courtrooms
    ]


def _invalid_assignments():
    from .enums import CourtLevel
    from .models import CourtroomAssignment, RoleAssignment, assignment_problems

    warnings = []
    for assignment in (
        RoleAssignment.objects.filter(is_active=True, user__is_active=True)
        .select_related("organization", "role", "user")
        .order_by("created_at")
    ):
        problems = assignment_problems(assignment.user_id, assignment.organization, assignment.role)
        if problems:
            warnings.append(
                Warning(
                    f"Role assignment {assignment}: {'; '.join(problems.values())}",
                    hint="Fix or deactivate it in admin.",
                    obj=assignment,
                    id="organizations.W002",
                )
            )
    for assignment in (
        CourtroomAssignment.objects.filter(is_active=True, user__is_active=True)
        .exclude(courtroom__court_level=CourtLevel.COURTROOM)
        .select_related("courtroom", "user")
    ):
        warnings.append(
            Warning(
                f"Courtroom assignment {assignment}: {assignment.courtroom.code} is not a courtroom.",
                hint="Fix or deactivate it in admin.",
                obj=assignment,
                id="organizations.W002",
            )
        )
    return warnings


def _roles_without_actions():
    from .models import CourtRole

    return [
        Warning(
            f"Court role {role} has no actions.",
            obj=role,
            id="organizations.W003",
        )
        for role in CourtRole.objects.filter(is_active=True, actions__isnull=True)
        .select_related("establishment")
        .order_by("code")
    ]


def _undeclared_actions():
    from .models import CourtRoleAction

    codes = sorted(
        code
        for code in CourtRoleAction.objects.order_by().values_list("action", flat=True).distinct()
        if not court_actions.is_registered(code)
    )
    return [
        Warning(
            f"Court roles hold {code!r}, which no module declares; it is ignored.",
            hint=(
                "Remove it with a data migration calling "
                "apps.organizations.migration_ops.remove_action_from_roles."
            ),
            id="organizations.W004",
        )
        for code in codes
    ]
