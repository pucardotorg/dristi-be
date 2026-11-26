"""Who may see and do what (spec 0033 #2, #15.4).

Everything that decides access goes through this module; views, serializers
and services never filter by user themselves. Membership is read from
``ports`` at the moment of the request, so someone removed from a case loses
every read and action at once (#2.1).

Order of checks on every filer action (#5.3): can the caller see it
(``404 E00105``) → is the action allowed in this status (``409 E13001``) → may
this caller take it (``403``) → the payload (``400``).
"""

from django.db.models import Q
from rest_framework.exceptions import NotFound

from . import ports
from .enums import CIRCLE_ONLY_STATUSES, SUBMITTED_STATUSES, ApplicationStatus
from .models import Application, OfficeMembership


def access_for(application, user):
    return ports.case_access(application.case_id, user)


def in_drafting_circle(application, user, access=None) -> bool:
    """The creator, *Raised by*, the creator's advocates, the *Raised by*'s clerks (#2.1).

    Only while the user is still a drafter on the application's side.
    """
    access = access or access_for(application, user)
    if not access.is_drafter or access.side != application.side:
        return False
    if user.pk in (application.created_by_id, application.raised_by_id):
        return True
    # Every advocate the creator works for (a clerk's draft, read by the advocate).
    if user.pk in set(ports.office_advocate_user_ids(application.created_by)):
        return True
    # A clerk or junior of the *Raised by* advocate, or of the advocate who created it.
    return bool(
        set(access.works_for) & {application.raised_by_id, application.created_by_id} - {None}
    )


def on_side(application, user, access=None) -> bool:
    """Anyone with an active relationship on the application's side (``ALC-29``)."""
    access = access or access_for(application, user)
    return access.is_on_side and access.side == application.side


def is_signer(application, user, access=None) -> bool:
    """Exactly *Raised by*, while an advocate or party in person on the side (``ALC-28``)."""
    if not application.raised_by_id or user.pk != application.raised_by_id or ports.is_clerk(user):
        return False
    access = access or access_for(application, user)
    return access.is_advocate_or_pip and access.side == application.side


def is_court_reader(application, user) -> bool:
    return ports.is_court_reader(user, application.case.court_id)


def can_see(application, user, access=None) -> bool:
    """Visibility by status (#2.3)."""
    status = application.status
    if status in CIRCLE_ONLY_STATUSES:
        return in_drafting_circle(application, user, access)
    if status == ApplicationStatus.PENDING_PAYMENT:
        return on_side(application, user, access) or in_drafting_circle(application, user, access)
    access = access or access_for(application, user)
    return access.is_case_reader or is_court_reader(application, user)


def get_visible(application_id, user, *, queryset=None):
    """The application, or ``404 E00105`` when the caller may not see it (#15.4)."""
    queryset = queryset if queryset is not None else Application.objects.all()
    application = (
        queryset.select_related(
            "application_type", "case", "case__court", "created_by", "raised_by"
        )
        .filter(pk=application_id)
        .first()
    )
    if application is None or not can_see(application, user):
        raise NotFound("Application not found.")
    return application


def visible_on_case(case_id, user, queryset=None):
    """The case's applications ``user`` may see (#2.3), as a queryset."""
    from apps.cases.models import Case

    queryset = queryset if queryset is not None else Application.objects.all()
    queryset = queryset.filter(case_id=case_id)
    access = ports.case_access(case_id, user)
    court_id = Case.objects.filter(pk=case_id).values_list("court_id", flat=True).first()
    reader = access.is_case_reader or ports.is_court_reader(user, court_id)
    if not reader:
        return queryset.none()
    visible = Q(status__in=SUBMITTED_STATUSES)
    if access.is_on_side:
        visible |= Q(status=ApplicationStatus.PENDING_PAYMENT, side=access.side)
    if access.is_drafter:
        visible |= Q(status__in=CIRCLE_ONLY_STATUSES, side=access.side) & circle_q(user, access)
        visible |= Q(status=ApplicationStatus.PENDING_PAYMENT, side=access.side) & circle_q(
            user, access
        )
    return queryset.filter(visible)


def circle_q(user, access):
    """The applications whose drafting circle holds ``user`` (#2.1), side checked by the caller."""
    office = OfficeMembership.objects.filter(is_active=True, advocate__user=user).values(
        "member_id"
    )
    bosses = list(access.works_for)
    return (
        Q(created_by=user)
        | Q(raised_by=user)
        | Q(created_by__in=office)
        | Q(raised_by__in=bosses)
        | Q(created_by__in=bosses)
    )
