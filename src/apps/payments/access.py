"""Who may see and pay a demand — TEMPORARY rule (spec 0017 #13).

==============================================================================
TODO(case-person-relationship): replace this module's rule.
==============================================================================

Spec 0017 #13 scopes every demand to its case: anyone with an *active*
``CasePersonRelationship`` (spec 0003) on ``Demand.case`` — advocate, clerk,
litigant, PoA holder, party in person — may list, retrieve and pay it, whatever
``Demand.user_id`` says; everyone else gets ``404 E00105``.

Neither ``apps.cases`` nor ``CasePersonRelationship`` exists on main yet, so
until they do, "involved in the case" is approximated per demand:

* a user sees a demand they raised (``created_by``) or are directed to pay
  (``user_id``), and every payment against it;
* raising a demand over REST is allowed on any ``case_id`` (there is nothing to
  check the case against); the caller becomes its creator.

This is narrower than the spec — two advocates on one case do not see each
other's demands — and never wider, so nothing leaks while the rule is in place.

Everything that decides access goes through the three functions below; the
views, serializers and services never filter by user themselves. When the
relationship model lands, the target implementation is::

    def involved_case_ids(user):
        return CasePersonRelationship.objects.active().filter(
            person=user
        ).values("case_id")

    def visible_demands(user, queryset=None):
        queryset = Demand.objects.all() if queryset is None else queryset
        return queryset.filter(case_id__in=involved_case_ids(user))

    def can_raise_on_case(user, case_id):
        return involved_case_ids(user).filter(case_id=case_id).exists()

and the tests marked ``TODO(case-person-relationship)`` in
``tests/test_access.py`` change with it.
"""

from django.db.models import Q, QuerySet

from .models import Demand, Payment


def visible_demands(user, queryset: QuerySet | None = None) -> QuerySet:
    """Demands ``user`` may list, retrieve and pay."""

    queryset = Demand.objects.all() if queryset is None else queryset
    if user is None or not user.is_authenticated:
        return queryset.none()
    # TODO(case-person-relationship): filter by the cases the user is involved in.
    return queryset.filter(Q(created_by=user) | Q(user_id=user.pk))


def visible_payments(user, queryset: QuerySet | None = None) -> QuerySet:
    """Payments on demands ``user`` may see."""

    queryset = Payment.objects.all() if queryset is None else queryset
    return queryset.filter(demand__in=visible_demands(user).values("pk"))


def can_raise_on_case(user, case_id) -> bool:
    """Whether ``user`` may raise a demand on ``case_id`` over REST."""

    # TODO(case-person-relationship): require an active relationship on the case.
    return bool(user and user.is_authenticated and case_id)
