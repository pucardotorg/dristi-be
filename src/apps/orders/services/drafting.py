"""Drafting: create, type, text, title, linked documents, discard (#5)."""

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.api.errors import BusinessError
from apps.cases import selectors as case_selectors
from apps.cases.models import Case, CaseStatus
from apps.hearings import selectors as hearing_selectors
from apps.hearings.exceptions import HearingError
from apps.hearings.services import listing

from .. import conf, errors, ports, rendering
from ..enums import (
    SHORTCUT_SCOPE_ORDER_TEXT,
    EnteredFrom,
    ItemSource,
    OrderStatus,
    TaskKey,
)
from ..models import Order, OrderItemType, OrderLinkedDocument, OrderType
from . import common, items, next_hearing

# Which screen an order starts from decides its preselected type (``OTY-03``).
FROM_HEARING = "HEARING"
FROM_APPLICATION_ONBOARDING = "APPLICATION_ONBOARDING"

# Items a preset adds in advance (``ORD-10a``, cognizance cheat sheet §6).
COGNIZANCE_PRESETS = {
    "TAKE_COGNIZANCE": ("COGNIZANCE", "ISSUE_OF_SUMMONS"),
    "ISSUE_NOTICE": ("ISSUE_OF_NOTICE",),
    "DISMISS_CASE": ("DISMISS_CASE",),
}
APPLICATION_PRESETS = {
    "ACCEPT": "ACCEPT_APPLICATION",
    "REJECT": "REJECT_APPLICATION",
    "DISMISS": "DISMISS_APPLICATION",
    "ACCEPT_BAIL": "ACCEPTANCE_OF_BAIL",
}


def offered_types(case_id):
    """Return the active order types the case's state offers (#2.2)."""
    state = case_selectors.state_code(case_id)
    return list(OrderType.objects.active().filter(state_code=state).order_by("code"))


def resolve_type(case_id, *, preselect=None, code=None):
    """Return the order type: the one asked for if offered, else preselected, else Normal (#5.8)."""
    types = offered_types(case_id)
    if code:
        for order_type in types:
            if order_type.code == code:
                return order_type
        raise BusinessError(errors.ORDER_TYPE_NOT_OFFERED, field="order_type")
    if preselect:
        for order_type in types:
            if preselect in order_type.preselect_from:
                return order_type
    for order_type in types:
        if order_type.code == "NORMAL":
            return order_type
    raise BusinessError(errors.ORDER_TYPE_NOT_OFFERED, field="order_type")


def _new_order(case, court_id, order_type, hearing_id, actor):
    return Order(
        case=case,
        court_id=court_id,
        hearing_id=hearing_id,
        order_type=order_type,
        title=order_type.default_title,
        created_by=actor,
        updated_by=actor,
    )


def _open_draft_task(order):
    ports.open_task(
        order.pk,
        TaskKey.DRAFT_ORDER,
        title=f"Draft order — {order.title}",
        role="ORDER_DRAFTER",
        court_id=order.court_id,
    )


def _save_new(order, actor, reason):
    order.updated_by = actor
    order._history_user = actor
    order._change_reason = reason
    order.save()


def create_in_hearing(*, hearing_id, actor, order_type_code=None, require_started=True):
    """Return ``(order, created)`` for the hearing's draft order (#5.1).

    The hearing must have been started (``E14004``), even when it already has a
    draft, except for the cause list's bulk next hearing, which creates the draft
    to hold its value (``PLC-05``). If it has a live order, that order is returned,
    so everyone opening the listing works one draft (``DFT-01``).
    """
    hearing = hearing_selectors.get_hearing(hearing_id)
    if hearing is None:
        raise NotFound("Hearing not found.")
    if require_started and hearing.started_at is None:
        raise BusinessError(errors.HEARING_NOT_STARTED)
    existing = live_order_for_hearing(hearing_id)
    if existing is not None:
        return existing, False
    case = Case.objects.get(pk=hearing.case_id)
    order_type = resolve_type(case.pk, preselect=FROM_HEARING, code=order_type_code)
    try:
        with transaction.atomic():
            order = _new_order(case, hearing.court_id, order_type, hearing.id, actor)
            _save_new(order, actor, "draft created")
            try:
                listing.attach_order(hearing_id=hearing.id, order_id=order.pk, actor=actor)
            except HearingError as exc:
                raise common.hearing_error(exc) from exc
            _open_draft_task(order)
    except IntegrityError:
        # Someone else created this hearing's draft in the same moment: use theirs.
        existing = live_order_for_hearing(hearing_id)
        if existing is None:
            raise
        return existing, False
    return order, True


def live_order_for_hearing(hearing_id):
    """Return the hearing's order unless it was discarded (``DFT-01``)."""
    return (
        Order.objects.filter(hearing_id=hearing_id)
        .exclude(status=OrderStatus.DISCARDED)
        .select_related("order_type", "court")
        .first()
    )


def create_outside_hearing(*, case_id, actor, preset=None, order_type_code=None):
    """Create a new draft on the case, outside any hearing (#5.2).

    The case must be registered and in a courtroom (``E14003``). Every call makes
    a new draft (``DFT-03``). A preset loads items in advance, removable like any
    other (``ORD-10a``); it is not stored.
    """
    case = Case.objects.filter(pk=case_id).first()
    if case is None:
        raise NotFound("Case not found.")
    if case.status != CaseStatus.REGISTERED or case.court_id is None:
        raise BusinessError(errors.CASE_NOT_IN_COURTROOM)
    preset = preset or {}
    onboarding = preset.get("kind") == "APPLICATION" and bool(preset.get("onboarding"))
    order_type = resolve_type(
        case.pk,
        preselect=FROM_APPLICATION_ONBOARDING if onboarding else None,
        code=order_type_code,
    )
    with transaction.atomic():
        order = _new_order(case, case.court_id, order_type, None, actor)
        next_hearing.default_from_listed(order, actor)
        _save_new(order, actor, "draft created")
        order = common.lock_order(order.pk)
        _add_preset_items(order, preset, actor)
        _open_draft_task(order)
    return order


def _add_item(order, code, actor, *, target_id=None):
    item_type = OrderItemType.objects.get(code=code)
    items.add_locked(order, item_type, target_id=target_id, source=ItemSource.PRESET, actor=actor)


def _add_preset_items(order, preset, actor):
    kind, action = preset.get("kind"), preset.get("action")
    if not kind:
        return
    if kind == "COGNIZANCE":
        codes = COGNIZANCE_PRESETS.get(action)
        if codes is None:
            raise errors.ITEM_VALUES_INVALID.validation_error(
                {"preset.action": ["Unknown cognizance action."]}
            )
        application_id = preset.get("delay_application_id")
        if (
            action == "TAKE_COGNIZANCE"
            and application_id
            and case_selectors.delay_applicable(order.case_id)
        ):
            _add_item(order, "ACCEPT_APPLICATION", actor, target_id=application_id)
        for code in codes:
            _add_item(order, code, actor)
    elif kind == "APPLICATION":
        code = APPLICATION_PRESETS.get(action)
        if code is None or not preset.get("application_id"):
            raise errors.ITEM_VALUES_INVALID.validation_error(
                {"preset": ["An application preset needs an action and an application_id."]}
            )
        _add_item(order, code, actor, target_id=preset["application_id"])
    else:
        raise errors.ITEM_VALUES_INVALID.validation_error({"preset.kind": ["Unknown preset."]})


def edit_text(order_id, text, *, actor, text_version=None):
    """Save the order text, sanitised, as it is typed (#5.3, #5.4).

    Idempotent: the same text is a no-op that does not bump the version
    (``ORD-20``). A change to an order whose data is marked complete reopens it
    (``SND-06``).
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "edit_text")
        common.check_version(order, "text", text_version)
        return edit_text_locked(order, text, actor, reason="text saved", autosave=True)


def append_text(order_id, text, *, actor):
    """Append ``text`` to the end of the order text (bulk text, #10.4); a text edit (``SND-06``)."""
    with transaction.atomic():
        order = common.lock_order(order_id)
        return edit_text_locked(order, f"{order.text}{rendering.sanitize_html(text)}", actor)


def edit_text_locked(order, text, actor, *, reason="text appended", autosave=False):
    """``edit_text`` for a caller that already holds the order's lock.

    An ``autosave`` (the client saves every few seconds, ``ORD-20``) writes no
    history row unless it reopens the order data: the row of the next send,
    move back, sign, trigger or discard holds the text then (#12.3). The latest
    save's author and time stay on the order (``text_saved_by``, ``text_saved_at``).
    """
    common.require_action(order, "edit_text")
    clean = rendering.sanitize_html(text)
    if len(clean.encode()) > conf.text_max_bytes():
        raise BusinessError(errors.ORDER_TEXT_TOO_LARGE, field="text")
    if clean == order.text:
        return order
    order.text = clean
    order.text_version += 1
    order.text_saved_by = actor
    order.text_saved_at = timezone.now()
    reopened = order.data_complete
    if reopened:
        order.data_complete = False
        order.data_completed_by = None
        order.data_completed_at = None
        order.data_version += 1
    common.save_order(order, actor, reason, history=not autosave or reopened)
    return order


def edit_title(order_id, title, *, actor):
    """Set the title; from then on it never changes by itself (#5.5, ``TIT-07``)."""
    title = (title or "").strip()
    if not title or len(title) > 255:
        raise errors.ITEM_VALUES_INVALID.validation_error(
            {"title": ["Enter a title of at most 255 characters."]}
        )
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "edit_title")
        if title != order.title:
            # A PDF prepared for signing carries the old title: drop it, so a signature
            # begun on it can never be recorded (as ``change_type`` does).
            order.signing_file_id = ""
        order.title = title
        order.title_overridden = True
        common.save_order(order, actor, "title edited")
        return order


def link_document(order_id, document_id, *, actor):
    """Link a case document to the order (#5.6, ``ORD-17``)."""
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "link_document")
        if not order.order_type.allows_linked_documents:
            raise BusinessError(errors.LINKS_NOT_ALLOWED_FOR_TYPE)
        known = {str(doc.id) for doc in case_selectors.case_documents(order.case_id)}
        if str(document_id) not in known:
            raise BusinessError(errors.DOCUMENT_NOT_ON_CASE, field="document_id")
        link, _ = OrderLinkedDocument.objects.get_or_create(
            order=order, document_id=document_id, defaults={"created_by": actor}
        )
        return link


def unlink_document(order_id, document_id, *, actor):
    """Remove a document link (#5.6)."""
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "link_document")
        OrderLinkedDocument.objects.filter(order=order, document_id=document_id).delete()


def discard(order_id, *, actor):
    """Discard a draft: the held date is released and the task expires (#5.7, ``DFT-06``).

    Nothing is recorded on the case. A hearing whose order was discarded may get a new one.
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "discard")
        next_hearing.release_on_discard(order, actor)
        order.status = OrderStatus.DISCARDED
        order.discarded_by = actor
        order.discarded_at = timezone.now()
        common.save_order(order, actor, "discarded")
        if order.hearing_id:
            listing.detach_order(hearing_id=order.hearing_id, order_id=order.pk, actor=actor)
        ports.expire_task(order.pk, TaskKey.DRAFT_ORDER)
        return order


def change_type(order_id, type_code, *, actor, remove_linked_documents=False):
    """Change the order's type until it is signed (#5.8, ``OTY-05``).

    A type that allows no links removes an order's links only with
    ``remove_linked_documents`` (``E14025``). A type with no separate diary
    entry reads the entry as the order text without touching the stored
    ``diary_same_as_text`` and ``diary_text``, so changing back restores them
    (``DEN-03``). The type changes nothing else (``OTY-02``).
    """
    with transaction.atomic():
        order = common.lock_order(order_id)
        common.require_action(order, "change_type")
        order_type = resolve_type(order.case_id, code=type_code)
        if order_type.pk == order.order_type_id:
            return order
        links = list(order.linked_documents.all())
        if links and not order_type.allows_linked_documents:
            if not remove_linked_documents:
                raise common.ProblemsError(
                    errors.LINKED_DOCUMENTS_WOULD_BE_REMOVED,
                    [("linked_documents", str(link.document_id)) for link in links],
                )
            order.linked_documents.all().delete()
        order.order_type = order_type
        if order.number:
            # A number allotted on a signing attempt belongs to the old type's series.
            order.number = ""
        # A PDF prepared for signing carries the old type's heading and number: drop it,
        # so a signature begun on it can never be recorded (as ``move_to_draft`` does).
        order.signing_file_id = ""
        items.recompute_title(order)
        # The page's heading changed: viewers' next ``/changes/`` poll must see it (#5.4).
        # The type is the drafter's, so the drafter's version moves, never the filler's.
        order.text_version += 1
        common.save_order(order, actor, f"type changed to {order_type.code}")
        return order


__all__ = [
    "EnteredFrom",
    "SHORTCUT_SCOPE_ORDER_TEXT",
    "append_text",
    "change_type",
    "create_in_hearing",
    "create_outside_hearing",
    "discard",
    "edit_text",
    "edit_title",
    "link_document",
    "unlink_document",
]
