"""Who may sign what (spec 0015 #6.1).

Whether a user may sign an order, a judgment or a filing is knowledge of the
module that owns that entity, so this module does not hardcode it. Owning
modules register an authorizer — in code at app-ready time, or as a dotted path
in ``ESIGN_ENTITY_AUTHORIZERS`` — and this module asks. An entity type with no
authorizer is not gated here; the endpoint's authentication still applies.
"""

from django.utils.module_loading import import_string

from . import conf
from .exceptions import ESignNotPermitted

_registry: dict[str, object] = {}


def register_entity_authorizer(entity_type: str, authorizer) -> None:
    """Register ``authorizer`` as the gate for ``entity_type``."""

    if not callable(authorizer):
        raise TypeError("An entity authorizer must be callable.")
    _registry[str(entity_type)] = authorizer


def unregister_entity_authorizer(entity_type: str) -> None:
    """Remove the authorizer registered for ``entity_type``, if any."""

    _registry.pop(str(entity_type), None)


def resolve_authorizer(entity_type: str):
    """Return the authorizer for ``entity_type``, or ``None``.

    Settings win over the in-process registry, so a deployment can always
    override what an app registered.
    """

    path = conf.entity_authorizers().get(str(entity_type))
    if path:
        return import_string(path) if isinstance(path, str) else path
    return _registry.get(str(entity_type))


def check_can_sign(*, user, entity_type: str, entity_id: str, organization_id=None) -> None:
    """Raise :class:`ESignNotPermitted` unless ``user`` may sign the entity."""

    authorizer = resolve_authorizer(entity_type)
    if authorizer is None:
        return

    allowed = authorizer(
        user=user,
        entity_type=entity_type,
        entity_id=entity_id,
        organization_id=organization_id,
    )
    if not allowed:
        raise ESignNotPermitted()
