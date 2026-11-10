"""Find the binding that applies to a court establishment (spec 0024 #2.4)."""

from django.db.models import Q

from .models import ScrutinyRuleBinding


def resolve_binding(decision, establishment):
    """Return the active binding for ``decision`` at ``establishment``, or None.

    The first active binding on the establishment, then on each ancestor from
    the nearest up, then the national default. ``establishment`` may be None,
    which resolves to the national default alone.
    """
    chain = []
    if establishment is not None:
        # get_ancestors() runs root first; resolution runs nearest first.
        chain = [establishment, *reversed(establishment.get_ancestors())]
    bindings = {
        binding.organization_id: binding
        for binding in ScrutinyRuleBinding.objects.active().filter(
            Q(organization__in=chain) | Q(organization__isnull=True), decision=decision
        )
    }
    for organization_id in [*(organization.pk for organization in chain), None]:
        if organization_id in bindings:
            return bindings[organization_id]
    return None
