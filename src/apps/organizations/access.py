"""The one court-access check helper (spec 0029 #7).

Checks are made in services, so a step is checked the same way whether it
arrives through the API, a Dramatiq task or a workflow engine. A view may call
the same helper early. Read access is not checked here: a caller who may not
read a case is told it does not exist (404, #6.1).

There is no system user that holds actions: a step the system takes runs
through a service entry point that never calls these.
"""

from django.core.exceptions import ImproperlyConfigured

from apps.api.errors import BusinessError

from . import court_actions, selectors


def require(user, action, organization_id, *, error, process_type=None, channel=None):
    """Raise ``BusinessError(error)`` unless ``user`` may take ``action`` at the organization.

    ``error`` is the owning module's code. ``process_type`` and ``channel``
    filter a scoped action (#5.5).
    """
    allowed = selectors.can(
        user, action, organization_id, process_type=process_type, channel=channel
    )
    if not allowed:
        raise BusinessError(error)


def require_any(user, actions, organization_id, *, error):
    """Raise ``BusinessError(error)`` unless ``user`` is allowed at least one of ``actions`` there.

    For a step that is not itself an action (#3.3): the module names the
    actions of the duty the step belongs to. It takes no scope, so ``actions``
    may not include a scoped action.
    """
    resolved = [court_actions.resolve(action) for action in actions]
    if not resolved:
        raise ImproperlyConfigured("require_any needs at least one action.")
    scoped = [action.code for action in resolved if action.scoped]
    if scoped:
        raise ImproperlyConfigured(
            f"require_any takes no scope, so it cannot check scoped action(s) {', '.join(scoped)}."
        )
    if not any(selectors.can(user, action, organization_id) for action in resolved):
        raise BusinessError(error)
