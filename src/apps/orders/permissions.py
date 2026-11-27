"""Who may read and act on orders (spec 0039 #2.1, #11.4).

* Court staff of a courtroom hold at least one court role there and read every
  order of it (``RLE-06``). Each action needs its own role (``403 E14019``).
* Parties read their case's signed orders and nothing else (``PUB-02``).
* Anyone else, staff of another courtroom included, is told the order does not
  exist (``404 E00105``), so the API never reveals one does.

Roles are read for the order's courtroom only (``RLE-02b``), through
``ports.court_roles``.
"""

from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.cases.selectors import case_ids_visible_to

from . import errors, ports
from .enums import OrderRole, OrderStatus, RoznamaStatus
from .models import Order

D, F, S, N = (
    OrderRole.ORDER_DRAFTER,
    OrderRole.ORDER_DATA_FILLER,
    OrderRole.ORDER_SIGNER,
    OrderRole.NEXT_HEARING_SETTER,
)

# The role(s) each action needs in the order's courtroom; any one of them is enough (#2.1, #11.1).
ACTION_ROLES = {
    "create": (D,),
    "edit_text": (D,),
    "edit_title": (D, F),
    "change_type": (D,),
    "link_document": (D,),
    "send_for_signing": (D,),
    "move_to_draft": (D,),
    "discard": (D,),
    "bulk_text": (D,),
    "add_item": (F,),
    "edit_item": (F,),
    "remove_item": (F,),
    "confirm_item": (F,),
    "edit_diary_entry": (F,),
    "mark_complete": (F,),
    "reopen": (F,),
    "bulk_items": (F,),
    "set_next_hearing": (N,),
    "bulk_next_hearing": (N,),
    "sign": (S,),
    "sign_roznama": (S,),
}


def court_roles(user, court_id):
    """Return the order roles ``user`` holds in the courtroom."""
    return ports.court_roles(user, court_id)


def is_staff(user, court_id):
    """Whether ``user`` holds any court role in the courtroom (``RLE-06``)."""
    return ports.is_court_staff(user, court_id)


def action_roles(action, order=None):
    """The roles ``action`` needs; ``order`` decides the one that depends on its state.

    The order signer also edits the diary entry, but only of a triggered order: a
    Gujarat Roznama awaiting its signature (#2.1, ``RZN-04``). Before triggering
    the entry is order data, the order data filler's alone (``ROL-02``).
    """
    if action == "edit_diary_entry" and order is not None and order.status == OrderStatus.TRIGGERED:
        return (F, S)
    return ACTION_ROLES[action]


def role_error(action, order=None):
    """The ``403 E14019`` naming the roles ``action`` needs."""
    names = " or ".join(role.label.lower() for role in action_roles(action, order))
    return BusinessError(
        errors.ROLE_REQUIRED, f"You need the {names} role in this courtroom to do this."
    )


def permits(roles, action, order=None):
    """Whether any of ``roles`` allows ``action`` (on ``order``, see ``action_roles``)."""
    return bool(set(action_roles(action, order)) & set(roles))


def require_role(user, court_id, action):
    """Refuse ``user`` unless they hold the role ``action`` needs in the courtroom (``E14019``).

    Court staff without it get ``403``; someone with no role in the courtroom
    at all gets the same ``403`` on an endpoint that names the courtroom, as
    there is no hidden order to protect.
    """
    roles = court_roles(user, court_id)
    if not permits(roles, action):
        raise role_error(action)
    return roles


def allowed_for_roles(actions, roles, order=None):
    """The ``allowed_actions`` the caller's roles permit (#10.2, ``ROL-06``)."""
    return [action for action in actions if permits(roles, action, order)]


def is_party(user, case_id):
    """Whether ``user`` has an active relationship with the case (spec 0003)."""
    return case_ids_visible_to(user).filter(pk=case_id).exists()


def visible_order(user, order_id):
    """Return ``(order, roles, is_staff)`` for an order the caller may see, or raise ``NotFound``.

    Staff see every order of their courtroom; a party sees a signed one only.
    """
    order = (
        Order.objects.select_related("order_type", "court", "case", "hearing")
        .filter(pk=order_id)
        .first()
    )
    if order is None:
        raise NotFound("Order not found.")
    if is_staff(user, order.court_id):
        return order, court_roles(user, order.court_id), True
    if order.status in (OrderStatus.SIGNED, OrderStatus.TRIGGERED) and is_party(
        user, order.case_id
    ):
        return order, frozenset(), False
    raise NotFound("Order not found.")


def actionable_order(user, order_id, action):
    """Return ``(order, roles)`` for an action on the order.

    Not visible: ``404``. A party, or staff without the role: ``403 E14019``.
    """
    order, roles, staff = visible_order(user, order_id)
    if not staff or not permits(roles, action, order):
        raise role_error(action, order)
    return order, roles


def can_sign_via_esign(*, user, entity_type, entity_id, organization_id=None, file_id=None):
    """The ``ORDER`` authorizer for ``apps.esign`` (#8.1): a signer, on an order awaiting signing.

    A direct call to ``/esign/_esign`` for an order is refused unless the user holds
    ``ORDER_SIGNER`` in its courtroom and the order is ``SENT_FOR_SIGNING`` — or,
    in Gujarat, is a triggered order whose Roznama awaits its signature (#8.4).
    ``file_id`` must be the document the order (or its Roznama) is about to sign.
    """
    order = (
        Order.objects.select_related("roznama").filter(pk=str(entity_id)).first()
        if _is_uuid(entity_id)
        else None
    )
    if order is None or not permits(court_roles(user, order.court_id), "sign"):
        return False
    roznama = getattr(order, "roznama", None)
    if order.status == OrderStatus.SENT_FOR_SIGNING:
        expected = order.signing_file_id
    elif (
        order.status == OrderStatus.TRIGGERED
        and roznama is not None
        and roznama.status == RoznamaStatus.AWAITING_SIGNATURE
    ):
        expected = roznama.signing_file_id
    else:
        return False
    # Only the current file: a signature on any other could never be recorded (#8.1), so
    # once ``signing_file_id`` is cleared even a retry is refused and the order is signed again.
    return bool(expected) and str(file_id or "") == expected


def _is_uuid(value):
    import uuid

    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True
