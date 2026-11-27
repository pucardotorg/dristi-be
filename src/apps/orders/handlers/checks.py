"""System check: every item with a workflow has a handler (spec 0039 #1.2, ``orders.E001``)."""

from django.core.checks import Error, Tags, Warning, register  # noqa: A004
from django.db import DatabaseError

from . import base


@register(Tags.database)
def check_workflow_items_have_handlers(app_configs, databases=None, **kwargs):
    """Fail when an active item type with ``has_workflow`` has no handler (``check --database``)."""
    if not databases:
        return []
    from ..models import OrderItemType

    try:
        codes = list(
            OrderItemType.objects.filter(is_active=True, has_workflow=True).values_list(
                "code", flat=True
            )
        )
    except DatabaseError:
        return []
    registered = base.registered()
    results = [
        Error(
            f"Order item {code} has a workflow but no handler is registered for it.",
            hint="Register an OrderItemHandler from the owning app's AppConfig.ready().",
            id="orders.E001",
        )
        for code in sorted(codes)
        if code not in registered
    ]
    pending = sorted(code for code in codes if code in registered and registered[code].placeholder)
    if pending:
        results.append(
            Warning(
                "Order items using a placeholder handler: " + ", ".join(pending) + ".",
                hint="Their workflow fails when an order is triggered until the owning module registers its handler.",
                id="orders.W001",
            )
        )
    return results
