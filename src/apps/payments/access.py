"""Who may see and pay a demand (spec 0017 #13).

Access follows ``Demand.case``: anyone involved in the case may list, retrieve
and pay its demands, whatever ``Demand.user_id`` says; everyone else gets
``404 E00105``. "Involved" is read from the cases module (spec 0020):

* the user who filed the case (``Case.created_by``);
* a complainant, accused or POA holder: an active ``CaseParticipant`` whose
  ``Person`` is the user's;
* an advocate: an active ``Representation`` of anyone on the case.

Witnesses are not included: #13 lists advocates, clerks, litigants, PoA holders
and parties in person. Clerks are not covered yet, because the cases module does
not link a clerk to an advocate or a case. A participant or advocate who is
removed from the case (soft-deleted, or with an end date that has passed) loses
access at once, including to payments they made.

Everything that decides access goes through the functions below; views,
serializers and services never filter by user themselves.
"""

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.cases.models import Case, CaseParticipant, ParticipantRole, Representation

from .models import Demand, Payment

# Roles that make a person's participation count as involvement in the case.
INVOLVED_ROLES = (
    ParticipantRole.COMPLAINANT,
    ParticipantRole.ACCUSED,
    ParticipantRole.POA_HOLDER,
)


def involved_case_ids(user) -> QuerySet:
    """Ids of the cases ``user`` is involved in, as a subquery."""

    now = timezone.now()
    as_participant = (
        CaseParticipant.objects.active()
        .filter(person__user=user, role__in=INVOLVED_ROLES)
        .filter(Q(end_date__isnull=True) | Q(end_date__gt=now))
        .values("case_id")
    )
    as_advocate = (
        Representation.objects.active()
        .filter(advocate__user=user)
        .filter(Q(to_date__isnull=True) | Q(to_date__gt=now))
        .values("case_id")
    )
    return Case.objects.filter(
        Q(created_by=user) | Q(pk__in=as_participant) | Q(pk__in=as_advocate)
    ).values("pk")


def visible_demands(user, queryset: QuerySet | None = None) -> QuerySet:
    """Demands ``user`` may list, retrieve and pay."""

    queryset = Demand.objects.all() if queryset is None else queryset
    if user is None or not user.is_authenticated:
        return queryset.none()
    return queryset.filter(case_id__in=involved_case_ids(user))


def visible_payments(user, queryset: QuerySet | None = None) -> QuerySet:
    """Payments on demands ``user`` may see."""

    queryset = Payment.objects.all() if queryset is None else queryset
    return queryset.filter(demand__in=visible_demands(user).values("pk"))


def can_raise_on_case(user, case_id) -> bool:
    """Whether ``user`` may raise a demand on ``case_id`` over REST."""

    if user is None or not user.is_authenticated or not case_id:
        return False
    return involved_case_ids(user).filter(pk=case_id).exists()
