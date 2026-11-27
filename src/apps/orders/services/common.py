"""Helpers every orders service shares: the lock, versions, stages, allowed actions (#4, #12.5)."""

from django.db import transaction
from rest_framework.exceptions import APIException, ErrorDetail

from apps.api.errors import BusinessError
from apps.hearings.exceptions import HearingError

from .. import conf, errors, rendering
from ..enums import DATA_EDITABLE_STATUSES, OrderStatus, RoznamaStatus, Stage
from ..models import Order


class ProblemsError(APIException):
    """A ``409`` listing several problems, each under its own field (``E14012``)."""

    status_code = 409

    def __init__(self, error, problems):
        self.error = error
        self.problems = list(problems)
        detail = {}
        for field, message in self.problems:
            detail.setdefault(field, []).append(ErrorDetail(message, code=error.code))
        super().__init__(detail=detail)


class ActionError(BusinessError):
    """``409 E14001`` carrying the ``allowed_actions`` the order's status allows, in ``errors[].data``."""

    def __init__(self, order, action, allowed):
        self.allowed_actions = allowed
        self.error_data = {"allowed_actions": list(allowed)}
        shown = ", ".join(name.replace("_", " ") for name in allowed) or "nothing"
        label = order.get_status_display().lower()
        super().__init__(
            errors.INVALID_ORDER_ACTION,
            f"An order that is {label} cannot {action.replace('_', ' ')}. It can: {shown}.",
        )


def hearing_error(exc: HearingError):
    """Surface an in-process hearings exception as its own API error, unchanged (#6.4)."""
    return BusinessError(exc.error, exc.message)


def lock_order(order_id, *, case=None):
    """Return the order with its row locked and re-read (#12.5).

    Raises ``Order.DoesNotExist`` when missing; callers map that to ``404``.
    """
    queryset = Order.objects.select_for_update(of=("self",)).select_related("order_type", "court")
    return queryset.get(pk=order_id)


def save_order(order, actor, reason, *, history=True):
    """Save ``order`` with who did it and why on its history row (#12.3).

    ``history=False`` writes no history row: for a text autosave, which the
    next lifecycle row records with its text.
    """
    if actor is not None and getattr(actor, "pk", None):
        order.updated_by = actor
        order._history_user = actor
    order._change_reason = reason[:100]
    if history:
        order.save()
    else:
        order.save_without_historical_record()


def send_on_commit(signal, order):
    """Send ``signal`` once the transaction commits; never on a rollback (#9.5).

    Robust: a failing receiver is logged and never stops the on-commit callbacks
    after it, such as the one that enqueues the order's runs.
    """
    order_id, case_id = order.pk, order.case_id

    # A named function, not a ``partial``: Django logs a robust callback's ``__qualname__``.
    def send_signal():
        signal.send(sender=None, order_id=order_id, case_id=case_id)

    transaction.on_commit(send_signal, robust=True)


def roznama_of(order):
    """Return the order's ``OrderRoznama``, or ``None`` (Gujarat only)."""
    from ..models import OrderRoznama

    return OrderRoznama.objects.filter(order_id=order.pk).first()


def stages(order, roznama=None):
    """Return the Pending-orders stages read from the order's facts (#4, ``PND-02``).

    An order sent for signing with incomplete data is in two stages at once. A
    triggered Gujarat order whose Roznama awaits its signature is also under
    *Awaiting signature*, as a Roznama (``PND-01``).
    """
    result = []
    if order.status == OrderStatus.DRAFT:
        result.append(Stage.DRAFTING)
    if order.status == OrderStatus.SENT_FOR_SIGNING:
        result.append(Stage.AWAITING_SIGNATURE)
    if (
        order.status in (OrderStatus.SENT_FOR_SIGNING, OrderStatus.SIGNED)
        and not order.data_complete
    ):
        result.append(Stage.ORDER_DATA_TO_FILL)
    if order.status == OrderStatus.TRIGGERED:
        result.append(Stage.TRIGGERED)
        if roznama is not None and roznama.status == RoznamaStatus.AWAITING_SIGNATURE:
            result.append(Stage.AWAITING_SIGNATURE)
    return [str(stage) for stage in result]


def allowed_actions(order, roznama=None):
    """Return the actions the order's status and data allow, before roles are applied (#4)."""
    status = order.status
    actions = []
    if status == OrderStatus.DRAFT:
        actions += [
            "edit_text",
            "edit_title",
            "change_type",
            "link_document",
            "set_next_hearing",
            "send_for_signing",
            "discard",
        ]
    elif status == OrderStatus.SENT_FOR_SIGNING:
        actions += ["edit_title", "change_type", "link_document", "move_to_draft", "sign"]
    elif status == OrderStatus.SIGNED:
        actions += ["edit_title"]
    if status in DATA_EDITABLE_STATUSES:
        if not order.data_complete:
            actions += ["add_item", "edit_item", "remove_item", "confirm_item", "mark_complete"]
        actions += ["edit_diary_entry"]
    if order.data_complete and status in (OrderStatus.DRAFT, OrderStatus.SENT_FOR_SIGNING):
        actions += ["reopen"]
    if (
        status == OrderStatus.TRIGGERED
        and roznama is not None
        and roznama.status == RoznamaStatus.AWAITING_SIGNATURE
    ):
        actions += ["edit_diary_entry", "sign_roznama"]
    return actions


def _allowed_for_error(order, roznama):
    """``allowed_actions`` for an ``E14001``, reading the Roznama a triggered order may await.

    Only a triggered order's actions depend on it, so no other refusal costs a query.
    """
    if roznama is None and order.status == OrderStatus.TRIGGERED:
        roznama = roznama_of(order)
    return allowed_actions(order, roznama)


def require_action(order, action, roznama=None):
    """Raise ``E14001`` unless ``action`` is allowed from the order's status (#4)."""
    allowed = _allowed_for_error(order, roznama)
    if action not in allowed:
        raise ActionError(order, action, allowed)


def require_data_editable(order):
    """Order data changes only before triggering and while not marked complete (#4, ``CMP-06``).

    Raises ``E14001`` for a triggered or discarded order, ``E14013`` for complete data.
    """
    if order.status not in DATA_EDITABLE_STATUSES:
        raise ActionError(order, "change order data", _allowed_for_error(order, None))
    if order.data_complete:
        raise BusinessError(errors.ORDER_DATA_COMPLETE)


def clean_text(text, *, field="text"):
    """Sanitise ``text`` as the order text is: its structure (``E14027``) and size (``E14020``).

    For every text that can reach a signed page or the order text: the order text,
    the diary entry and a shortcut's body (#3.1, #5.3).
    """
    clean = rendering.sanitize_html(text, field=field)
    if len(clean.encode()) > conf.text_max_bytes():
        raise BusinessError(errors.ORDER_TEXT_TOO_LARGE, field=field)
    return clean


def check_version(order, kind, expected):
    """Refuse a write made against an older copy: ``412 E14002`` (``DFT-02``).

    ``kind`` is ``"text"`` or ``"data"``; ``expected`` is the version the client
    loaded, or ``None`` for a service-side caller.
    """
    if expected is None:
        return
    current = order.text_version if kind == "text" else order.data_version
    if int(expected) != current:
        raise BusinessError(errors.ORDER_STALE)


def allowed_for_roles_view(order, roznama, roles):
    """The actions the order's status allows that ``roles`` also permit (``ROL-06``)."""
    from ..permissions import allowed_for_roles

    return allowed_for_roles(allowed_actions(order, roznama), roles, order)
