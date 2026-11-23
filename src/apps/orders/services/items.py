"""Order items: the catalogue for an order, and the one way to add, edit and remove them (#6).

``add`` is the only way in, whether a person, a preset, a bulk action or a later
reading layer adds an item (``ITM-12``). Availability, combinations and shape are
checked here, under the order lock, never by a screen alone. Mandatory fields are
checked only when the order data is marked complete (``VAR-05``, ``CMP-02``).
"""

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.api.errors import BusinessError
from apps.cases.selectors import order_context
from apps.hearings import selectors as hearing_selectors
from apps.hearings.models import HearingPurpose

from .. import errors, field_schema, handlers
from ..enums import Availability, FieldInput, ItemSource, RuleKind
from ..handlers.base import ItemContext, Problem
from ..handlers.builtin import NoWorkflowHandler
from ..models import OrderItem, OrderItemCombinationRule, OrderItemType
from . import common

NO_HANDLER = NoWorkflowHandler()
APPLICATION = "APPLICATION"
# Evaluated before EXCLUSIVE so a repeat reads "twice", not "both X and X".
RULE_ORDER = {RuleKind.NO_REPEAT: 0, RuleKind.ONE_PER_TARGET: 1, RuleKind.EXCLUSIVE: 2}


def handler_for(item_type):
    """Return the item's registered handler, or the no-op default for an item with no workflow."""
    return handlers.get(item_type.code) or NO_HANDLER


def context_for(order, *, item=None, source="", target_type="", target_id=None):
    """Build the handler's view of one item on one order."""
    return ItemContext(
        case_id=order.case_id,
        order_id=order.pk,
        hearing_id=order.hearing_id,
        target_type=item.target_type if item else target_type,
        target_id=item.target_id if item else target_id,
        item_id=item.pk if item else None,
        source=source,
    )


# -- Catalogue ---------------------------------------------------------------


def combination_reason(order, item_type, *, target_id=None, existing=None):
    """Return the configured message if adding ``item_type`` breaks a combination rule, else ``None``.

    ``existing`` is the order's items (defaults to reading them).
    """
    existing = list(order.items.select_related("item_type")) if existing is None else existing
    rules = sorted(
        OrderItemCombinationRule.objects.filter(is_active=True, item_types=item_type).distinct(),
        key=lambda rule: (RULE_ORDER[rule.kind], rule.code),
    )
    for rule in rules:
        members = set(rule.item_types.values_list("pk", flat=True))
        clashing = [item for item in existing if item.item_type_id in members]
        if rule.kind == RuleKind.NO_REPEAT:
            clashing = [item for item in clashing if item.item_type_id == item_type.pk]
        elif rule.kind == RuleKind.ONE_PER_TARGET:
            clashing = [
                item for item in clashing if target_id is not None and item.target_id == target_id
            ]
        if clashing:
            return rule.message.format(adding=item_type.label, existing=clashing[0].item_type.label)
    return None


def unavailable(
    order, item_type, *, source=ItemSource.PERSON, target_type="", target_id=None, existing=None
):
    """Return ``(code, message)`` if the item cannot be added now, else ``None`` (``ITM-03``).

    The handler's reason comes first, then the combination rules (``ITM-07``).
    """
    if not item_type.is_active:
        return "INACTIVE", "This order item is no longer offered."
    ctx = context_for(order, source=str(source), target_type=target_type, target_id=target_id)
    if reason := handler_for(item_type).unavailable_reason(ctx):
        return reason
    if message := combination_reason(order, item_type, target_id=target_id, existing=existing):
        return "COMBINATION_NOT_ALLOWED", message
    return None


def catalogue(order=None, *, search="", category=""):
    """Return every active item, with availability and *Suggested* when for an order (#6.1)."""
    queryset = OrderItemType.objects.filter(is_active=True).prefetch_related(
        "suggested_for_purposes"
    )
    if category:
        queryset = queryset.filter(category=category)
    if search:
        queryset = queryset.filter(label__icontains=search)
    purpose_code = ""
    existing = None
    if order is not None:
        existing = list(order.items.select_related("item_type"))
        if order.hearing_id:
            hearing = hearing_selectors.get_hearing(order.hearing_id)
            purpose_code = hearing.purpose_code if hearing else ""
    rows = []
    for item_type in queryset:
        row = {
            "code": item_type.code,
            "label": item_type.label,
            "category": item_type.category,
            "availability": item_type.availability,
            "target_type": item_type.target_type,
            "field_schema": item_type.field_schema,
            "suggested": False,
            "available": True,
            "unavailable_reason": None,
        }
        if order is not None:
            row["suggested"] = bool(purpose_code) and any(
                purpose.code == purpose_code for purpose in item_type.suggested_for_purposes.all()
            )
            reason = unavailable(order, item_type, existing=existing)
            if reason:
                row["available"] = False
                row["unavailable_reason"] = {"code": reason[0], "message": reason[1]}
        rows.append(row)
    return rows


# -- Values ------------------------------------------------------------------


def _party_ids(order, allowed_roles):
    context = order_context(order.case_id)
    roles = allowed_roles or list(context.parties)
    return {str(party.id) for role in roles for party in context.of_role(role)}


def record_keys(item_type):
    """The keys of the item's read-only fields, filled from the record and never typed."""
    return {
        key
        for key, field in field_schema.fields_of(item_type.field_schema).items()
        if field["input"] == FieldInput.RECORD
    }


def read_only_problems(item_type, typed):
    """Return a problem for each read-only field a person typed a value into."""
    return [
        Problem(f"values.{key}", "READ_ONLY", f"{key} is read from the record, not entered.")
        for key in sorted(record_keys(item_type) & set(typed))
    ]


def values_problems(order, item_type, values, handler, ctx, *, complete=False):
    """Return the problems with ``values`` as ``Problem`` rows (shape on save, more on complete)."""
    fields = field_schema.fields_of(item_type.field_schema)
    editable = field_schema.editable_fields(item_type.field_schema)
    problems = []
    for key in values:
        if key not in fields:
            problems.append(
                Problem(f"values.{key}", "UNKNOWN", f"{key} is not a field of this item.")
            )
    people_cache = {}
    for key, field in editable.items():
        value = values.get(key)
        if issue := field_schema.value_problem(field, value):
            problems.append(Problem(f"values.{key}", *issue))
            continue
        if field_schema.is_blank(value):
            continue
        kind = field["input"]
        if kind in (FieldInput.PARTY, FieldInput.PARTIES):
            roles = tuple(field.get("party_types") or ())
            people = people_cache.setdefault(roles, _party_ids(order, roles))
            chosen = [value] if kind == FieldInput.PARTY else value
            for person in chosen:
                if str(person) not in people:
                    problems.append(
                        Problem(
                            f"values.{key}",
                            "NOT_IN_CASE",
                            f"{field['label']}: this person is not one of those the case allows here.",
                        )
                    )
                    break
        elif kind == FieldInput.HEARING_PURPOSE:
            if not HearingPurpose.objects.active().filter(code=value).exists():
                problems.append(
                    Problem(
                        f"values.{key}", "INVALID_PURPOSE", "This hearing purpose is not active."
                    )
                )
    if complete:
        problems += mandatory_problems(fields, values)
    return problems + handler.validate(ctx, values, complete=complete)


def mandatory_problems(fields, values):
    """Return a ``REQUIRED`` problem for each mandatory field left unanswered (``CMP-02``)."""
    return [
        Problem(f"values.{key}", "REQUIRED", f"{field['label']} is required.")
        for key, field in fields.items()
        if field.get("mandatory")
        and field["input"] != FieldInput.RECORD
        and field_schema.is_blank(values.get(key))
    ]


def _raise_invalid(problems):
    detail = {}
    for problem in problems:
        detail.setdefault(problem.field, []).append(problem.message)
    raise errors.ITEM_VALUES_INVALID.validation_error(detail)


# -- Titles ------------------------------------------------------------------


def recompute_title(order):
    """Recompute the default title from the items, until someone edits it (#5.5, ``TIT-07``)."""
    if order.title_overridden:
        return
    labels = list(order.items.order_by("position").values_list("item_type__label", flat=True))
    if not labels:
        order.title = order.order_type.default_title
    elif len(labels) == 1:
        order.title = labels[0]
    else:
        order.title = f"{labels[0]} and other items"


# -- Writes ------------------------------------------------------------------


def add_locked(
    order,
    item_type,
    *,
    target_id=None,
    values=None,
    source=ItemSource.PERSON,
    actor=None,
    data_version=None,
):
    """Add an item to the locked ``order``: #6.2 steps 1-6. Returns the ``OrderItem``."""
    common.check_version(order, "data", data_version)
    common.require_data_editable(order)
    values = dict(values or {})
    target_type = APPLICATION if item_type.availability != Availability.DROPDOWN else ""

    if item_type.availability == Availability.CONTEXTUAL and target_id is None:
        raise BusinessError(errors.ITEM_TARGET_INVALID, field="target_id")
    if item_type.availability == Availability.DROPDOWN and target_id is not None:
        raise BusinessError(
            errors.ITEM_TARGET_INVALID, "This item applies to no application.", field="target_id"
        )
    existing = list(order.items.select_related("item_type"))
    if reason := unavailable(
        order,
        item_type,
        source=source,
        target_type=target_type,
        target_id=target_id,
        existing=existing,
    ):
        error = (
            errors.ITEM_COMBINATION_NOT_ALLOWED
            if reason[0] == "COMBINATION_NOT_ALLOWED"
            else errors.ITEM_NOT_AVAILABLE
        )
        raise BusinessError(error, reason[1], field="item_type")

    handler = handler_for(item_type)
    ctx = context_for(order, source=str(source), target_type=target_type, target_id=target_id)
    if target_id is not None:
        if problems := handler.validate_target(ctx):
            raise BusinessError(errors.ITEM_TARGET_INVALID, problems[0].message, field="target_id")
    if source != ItemSource.SYSTEM and (problems := read_only_problems(item_type, values)):
        _raise_invalid(problems)
    merged = {**handler.defaults(ctx), **values}
    if problems := values_problems(order, item_type, merged, handler, ctx):
        _raise_invalid(problems)

    position = (order.items.aggregate(top=Max("position"))["top"] or 0) + 1
    item = OrderItem(
        order=order,
        item_type=item_type,
        position=position,
        target_type=target_type if target_id is not None else "",
        target_id=target_id,
        values=merged,
        added_by_source=source,
        confirmed=source != ItemSource.READER,
        unconfirmed_fields=sorted(merged) if source == ItemSource.READER else [],
    )
    _save_item(item, actor, f"item added: {item_type.code}")
    recompute_title(order)
    order.data_version += 1
    common.save_order(order, actor, f"item added: {item_type.code}")
    return item


def _save_item(item, actor, reason):
    if actor is not None and getattr(actor, "pk", None):
        item.updated_by = actor
        item._history_user = actor
        if item._state.adding:
            item.created_by = actor
    item._change_reason = reason[:100]
    item.save()


def _item(order, item_id):
    item = order.items.select_related("item_type").filter(pk=item_id).first()
    if item is None:
        from rest_framework.exceptions import NotFound

        raise NotFound("Order item not found.")
    return item


def add(
    order_id,
    item_code,
    *,
    target_id=None,
    values=None,
    source=ItemSource.PERSON,
    actor=None,
    data_version=None,
):
    """Add an item to an order, under the order lock. See ``add_locked``."""
    item_type = OrderItemType.objects.filter(code=item_code).first()
    if item_type is None:
        raise BusinessError(errors.ITEM_NOT_AVAILABLE, "No such order item.", field="item_type")
    with transaction.atomic():
        order = common.lock_order(order_id)
        return add_locked(
            order,
            item_type,
            target_id=target_id,
            values=values,
            source=source,
            actor=actor,
            data_version=data_version,
        )


def update(order_id, item_id, values, *, source=ItemSource.PERSON, actor=None, data_version=None):
    """Replace an item's values (#6.2). A person's own edit confirms the fields they changed."""
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.check_version(order, "data", data_version)
        common.require_data_editable(order)
        item = _item(order, item_id)
        handler = handler_for(item.item_type)
        ctx = context_for(order, item=item, source=str(source))
        values = dict(values or {})
        kept = {key: item.values[key] for key in record_keys(item.item_type) if key in item.values}
        typed = {key: value for key, value in values.items() if kept.get(key) != value}
        if source != ItemSource.SYSTEM and (problems := read_only_problems(item.item_type, typed)):
            _raise_invalid(problems)
        values = {**kept, **values}
        if problems := values_problems(order, item.item_type, values, handler, ctx):
            _raise_invalid(problems)
        changed = {
            key for key in {*item.values, *values} if item.values.get(key) != values.get(key)
        }
        if source == ItemSource.READER:
            item.confirmed = False
            item.unconfirmed_fields = sorted({*item.unconfirmed_fields, *changed})
        else:
            item.unconfirmed_fields = [key for key in item.unconfirmed_fields if key not in changed]
        item.values = values
        _save_item(item, actor, f"item changed: {item.item_type.code}")
        order.data_version += 1
        common.save_order(order, actor, f"item changed: {item.item_type.code}")
        return item


def _close_gaps(order):
    for position, item in enumerate(order.items.order_by("position"), start=1):
        if item.position != position:
            item.position = position
            item.save(update_fields=["position", "updated_at"])


def remove_locked(order, item, *, actor=None):
    """Remove ``item`` from the locked order, close the gap and recompute the title (#6.2)."""
    code = item.item_type.code
    item.delete()
    _close_gaps(order)
    recompute_title(order)
    order.data_version += 1
    common.save_order(order, actor, f"item removed: {code}")


def remove(order_id, item_id, *, actor=None, data_version=None):
    """Remove an item and its future workflow (``ITM-09``). Never touches the text."""
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.check_version(order, "data", data_version)
        common.require_data_editable(order)
        item = _item(order, item_id)
        if item.added_by_source == ItemSource.SYSTEM:
            raise BusinessError(
                errors.INVALID_ORDER_ACTION,
                "This item follows from the next hearing. Change the next hearing instead.",
            )
        remove_locked(order, item, actor=actor)


def confirm(order_id, item_id, *, actor=None):
    """Confirm an item a reading layer added, and every field of it (#6.2)."""
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_data_editable(order)
        item = _item(order, item_id)
        item.confirmed = True
        item.unconfirmed_fields = []
        _save_item(item, actor, "item confirmed")
        order.data_version += 1
        common.save_order(order, actor, "item confirmed")
        return item


# -- Completion --------------------------------------------------------------


def completion_problems(order):
    """Return ``(field, message)`` for everything that stops the order data being complete (``CMP-02``).

    Catalogue-mandatory fields, each handler's own completeness checks, a
    contextual item's target, and any unconfirmed reading-layer item or field.
    """
    problems = []
    for item in order.items.select_related("item_type").order_by("position"):
        handler = handler_for(item.item_type)
        ctx = context_for(order, item=item)
        prefix = f"items[{item.position}]"
        found = list(
            values_problems(order, item.item_type, item.values, handler, ctx, complete=True)
        )
        if item.target_id is not None:
            found += handler.validate_target(ctx)
        if not item.confirmed or item.unconfirmed_fields:
            found.append(
                Problem("confirmed", "UNCONFIRMED", "Confirm what was filled in for this item.")
            )
        problems += [(f"{prefix}.{problem.field}", problem.message) for problem in found]
    return problems


def item_problems(order, item):
    """The problems of one item, for the order screen (``problems`` of #10.2)."""
    handler = handler_for(item.item_type)
    ctx = context_for(order, item=item)
    found = list(values_problems(order, item.item_type, item.values, handler, ctx, complete=True))
    if not item.confirmed or item.unconfirmed_fields:
        found.append(
            Problem("confirmed", "UNCONFIRMED", "Confirm what was filled in for this item.")
        )
    return found


__all__ = [
    "add",
    "add_locked",
    "catalogue",
    "completion_problems",
    "confirm",
    "context_for",
    "item_problems",
    "recompute_title",
    "remove",
    "remove_locked",
    "unavailable",
    "update",
]


def confirm_paid(order_id, item_id, *, user):
    """The paying side confirms they paid a witness batta; closes its task (#9.3, #11.1).

    Only a party on the paying side of a triggered order may. The money is not
    paid through the system: this is the confirmation that closes the task.
    """
    from rest_framework.exceptions import NotFound

    from apps.cases.models import CaseParticipant

    from .. import permissions, ports
    from ..enums import OrderStatus
    from ..models import OrderWorkflowRun

    order, _, _ = permissions.visible_order(user, order_id)
    item = order.items.select_related("item_type").filter(pk=item_id).first()
    if item is None or item.item_type.code != "WITNESS_BATTA":
        raise NotFound("Order item not found.")
    if order.status != OrderStatus.TRIGGERED:
        raise BusinessError(errors.INVALID_ORDER_ACTION, "The order has not been triggered.")
    roles = {"COMPLAINANT": ("COMPLAINANT", "POA_HOLDER"), "ACCUSED": ("ACCUSED",)}.get(
        item.values.get("paying_party"), ()
    )
    on_side = CaseParticipant.objects.active().filter(
        case_id=order.case_id, role__in=roles, person__user=user
    )
    if not on_side.exists():
        raise permissions.role_error("add_item")
    ports.complete_item_task(item.pk, "witness_batta")
    run = OrderWorkflowRun.objects.filter(order_item=item).first()
    if run is not None and "paid_confirmed_by" not in run.result:
        run.result = {
            **run.result,
            "paid_confirmed_by": str(user.pk),
            "paid_confirmed_at": timezone.now().isoformat(),
        }
        run.save(update_fields=["result", "updated_at"])
    return item
