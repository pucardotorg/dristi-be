"""Reads for the order screen, Pending orders, the case file and other modules (spec 0039 #10, #11).

Every list is batched: case summaries and hearings come in one call per page,
never per row (``CLS-13``). Other modules read an order through here and never
trust a signal's payload alone (#9.5).
"""

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.cases.selectors import case_documents, get_case_summaries, search_case_ids
from apps.hearings import selectors as hearing_selectors
from apps.hearings.models import HearingPurpose

from . import conf, ports
from .enums import NextHearingState, OrderRole, OrderStatus, RoznamaStatus, Stage
from .models import Order, OrderRoznama, OrderType
from .services import common, diary, items, next_hearing, signing

TABS = {
    "drafting": Stage.DRAFTING,
    "awaiting_signature": Stage.AWAITING_SIGNATURE,
    "order_data": Stage.ORDER_DATA_TO_FILL,
    "triggered": Stage.TRIGGERED,
}
# The label parties see on the case file for each status (view case ``ORD-04``-``ORD-06``).
PARTY_STATUS_LABELS = {
    OrderStatus.DRAFT: "Draft in progress",
    OrderStatus.SENT_FOR_SIGNING: "Pending signature",
    OrderStatus.SIGNED: "Published",
    OrderStatus.TRIGGERED: "Published",
}


def get_order(order_id):
    """Return the order with its type, court and case, or ``None``."""
    return (
        Order.objects.select_related("order_type", "court", "case", "hearing")
        .filter(pk=order_id)
        .first()
    )


def diary_entry(order_id):
    """Return the order's diary entry as HTML, composed on read (#6.6), or ``None``."""
    order = get_order(order_id)
    return diary.composed_entry(order) if order else None


def default_tab(roles):
    """The tab Pending orders opens on: the viewer's own move (``PND-04``)."""
    if OrderRole.ORDER_SIGNER in roles:
        return "awaiting_signature"
    if OrderRole.ORDER_DATA_FILLER in roles:
        return "order_data"
    return "drafting"


def _my_action(roles, stage, kind="ORDER"):
    if stage == Stage.DRAFTING and OrderRole.ORDER_DRAFTER in roles:
        return "continue_drafting"
    if stage == Stage.AWAITING_SIGNATURE and OrderRole.ORDER_SIGNER in roles:
        return "sign_roznama" if kind == "ROZNAMA" else "sign"
    if stage == Stage.ORDER_DATA_TO_FILL and OrderRole.ORDER_DATA_FILLER in roles:
        return "fill_order_data"
    return None


def _base(court_id):
    return Order.objects.filter(court_id=court_id).exclude(status=OrderStatus.DISCARDED)


def _in_tab(queryset, tab):
    if tab == "drafting":
        return queryset.filter(status=OrderStatus.DRAFT)
    if tab == "awaiting_signature":
        return queryset.filter(
            Q(status=OrderStatus.SENT_FOR_SIGNING)
            | Q(status=OrderStatus.TRIGGERED, roznama__status=RoznamaStatus.AWAITING_SIGNATURE)
        )
    if tab == "order_data":
        return queryset.filter(
            status__in=(OrderStatus.SENT_FOR_SIGNING, OrderStatus.SIGNED), data_complete=False
        )
    cutoff = timezone.now() - timedelta(days=conf.triggered_tab_days())
    return queryset.filter(status=OrderStatus.TRIGGERED, triggered_at__gte=cutoff)


def pending_counts(court_id):
    """Return the four tab counts (``PND-03``). An order may be in two tabs at once."""
    return {tab: _in_tab(_base(court_id), tab).distinct().count() for tab in TABS}


def badge(roles, counts):
    """The number of orders at the viewer's own stage, or ``None`` with no move here (``PND-04``)."""
    tab = default_tab(roles)
    mine = (
        OrderRole.ORDER_DRAFTER in roles
        or OrderRole.ORDER_SIGNER in roles
        or OrderRole.ORDER_DATA_FILLER in roles
    )
    return counts[tab] if mine else None


def pending_queryset(court_id, tab, search=""):
    """The Pending orders tab's orders, newest first, optionally searched by case or title."""
    queryset = _in_tab(_base(court_id), tab).select_related("order_type", "roznama").distinct()
    if search:
        case_ids = list(search_case_ids(search, court_id))
        queryset = queryset.filter(Q(title__icontains=search) | Q(case_id__in=case_ids))
    return queryset.order_by("-updated_at")


def pending_rows(orders, roles, tab):
    """Build the rows of one page of Pending orders; batched case and hearing reads (#10.1)."""
    orders = list(orders)
    summaries = get_case_summaries({order.case_id for order in orders})
    hearings = hearing_selectors.get_hearings({o.hearing_id for o in orders if o.hearing_id})
    states = {order.order_type.state_code for order in orders}
    # One grouped query, however many rows: a state with more than one type shows it (``PND-03``).
    type_counts = dict(
        OrderType.objects.filter(state_code__in=states, is_active=True)
        .values_list("state_code")
        .annotate(total=Count("pk"))
    )
    multi_type = {state for state, total in type_counts.items() if total > 1}
    rows = []
    for order in orders:
        roznama = getattr(order, "roznama", None)
        kind = (
            "ROZNAMA"
            if tab == "awaiting_signature"
            and order.status == OrderStatus.TRIGGERED
            and roznama is not None
            and roznama.status == RoznamaStatus.AWAITING_SIGNATURE
            else "ORDER"
        )
        stage_names = common.stages(order, roznama)
        stage = Stage(TABS[tab])
        summary = summaries.get(order.case_id)
        hearing = hearings.get(order.hearing_id)
        rows.append(
            {
                "id": order.pk,
                "kind": kind,
                "type": {"code": order.order_type.code, "label": order.order_type.label}
                if order.order_type.state_code in multi_type
                else None,
                "title": order.title,
                "case": {
                    "id": order.case_id,
                    "display_number": summary.display_number if summary else "",
                    "title": summary.title if summary else "",
                },
                "hearing": {
                    "id": hearing.id,
                    "date": hearing.hearing_date,
                    "sequence": hearing.sequence,
                }
                if hearing
                else None,
                "signature": signature_state(order),
                "order_data": "COMPLETE" if order.data_complete else "NOT_COMPLETE",
                "stages": stage_names,
                "my_action": _my_action(roles, stage, kind),
                "updated_at": order.updated_at,
            }
        )
    return rows


def signature_state(order):
    """``NOT_SENT``, ``AWAITING`` or ``SIGNED`` — the same for everyone (``PND-03``)."""
    if order.status == OrderStatus.DRAFT:
        return "NOT_SENT"
    if order.status == OrderStatus.SENT_FOR_SIGNING:
        return "AWAITING"
    return "SIGNED"


def whose_move(order, roznama=None):
    """A line saying whose move it is (``PND-08``)."""
    if order.status == OrderStatus.DRAFT:
        return "Being drafted by an order drafter"
    if order.status == OrderStatus.SENT_FOR_SIGNING:
        if order.data_complete:
            return "Awaiting signature by an order signer"
        return "Awaiting signature by an order signer, and order data by an order data filler"
    if order.status == OrderStatus.SIGNED:
        return "Order data to be completed by an order data filler"
    if (
        order.status == OrderStatus.TRIGGERED
        and roznama is not None
        and roznama.status == RoznamaStatus.AWAITING_SIGNATURE
    ):
        return "Roznama awaiting signature by an order signer"
    return ""


def order_detail(order, roles):
    """The order screen (#10.2): text, rendered page, items with problems, next hearing, actions."""
    roznama = OrderRoznama.objects.filter(order=order).first()
    summary = get_case_summaries([order.case_id]).get(order.case_id)
    hearing = hearing_selectors.get_hearing(order.hearing_id) if order.hearing_id else None
    documents = {str(doc.id): doc.name for doc in case_documents(order.case_id)}
    order_type = order.order_type
    attendance_complete = None
    if order.hearing_id:
        from apps.hearings.services import courtroom

        attendance_complete = courtroom.attendance_complete(order.hearing_id)
    item_rows = []
    for item in order.items.select_related("item_type").order_by("position"):
        item_rows.append(
            {
                "id": item.pk,
                "position": item.position,
                "item_type": {"code": item.item_type.code, "label": item.item_type.label},
                "target_id": item.target_id,
                "values": item.values,
                "source": item.added_by_source,
                "confirmed": item.confirmed,
                "unconfirmed_fields": item.unconfirmed_fields,
                "problems": [
                    {"field": p.field, "code": p.code, "message": p.message}
                    for p in items.item_problems(order, item)
                ]
                if not order.data_complete
                else [],
            }
        )
    actions = common.allowed_for_roles_view(order, roznama, roles)
    editing = None
    if order.text_saved_by_id and order.text_saved_at:
        editing = {"user": order.text_saved_by_id, "at": order.text_saved_at}
    return {
        "id": order.pk,
        "status": order.status,
        "stages": common.stages(order, roznama),
        "whose_move": whose_move(order, roznama),
        "type": {
            "code": order_type.code,
            "label": order_type.label,
            "allows_linked_documents": order_type.allows_linked_documents,
        },
        "title": order.title,
        "case": {
            "id": order.case_id,
            "display_number": summary.display_number if summary else "",
            "title": summary.title if summary else "",
            "stage": ports.current_stage(order.case_id),
        },
        "hearing": {
            "id": hearing.id,
            "date": hearing.hearing_date,
            "sequence": hearing.sequence,
            "purpose": {"code": hearing.purpose_code, "label": hearing.purpose_label},
        }
        if hearing
        else None,
        "text": order.text,
        "rendered_html": signing.render_page_html(order),
        "items": item_rows,
        "next_hearing": next_hearing.view(order),
        "attendance_complete": attendance_complete,
        "diary_entry": {
            "label": order_type.diary_entry_label,
            "same_as_text": order.diary_same_as_text,
            "separate_allowed": order_type.separate_diary_entry,
            "text": diary.composed_entry(order),
        },
        "roznama": {
            "status": roznama.status,
            "number": roznama.number,
            "signed_file_id": roznama.signed_file_id,
        }
        if roznama
        else None,
        "linked_documents": [
            {"document_id": link.document_id, "name": documents.get(str(link.document_id), "")}
            for link in order.linked_documents.all()
        ],
        "data_complete": order.data_complete,
        "number": order.number,
        "order_date": order.order_date,
        "signed_file_id": order.signed_file_id,
        "text_version": order.text_version,
        "data_version": order.data_version,
        "editing": editing,
        "allowed_actions": actions,
    }


def party_view(order):
    """What a party reads of a signed order: no drafts, no order data."""
    return {
        "id": order.pk,
        "type": {"code": order.order_type.code, "label": order.order_type.label},
        "title": order.title,
        "number": order.number,
        "order_date": order.order_date,
        "status": PARTY_STATUS_LABELS[order.status],
        "signed_file_id": order.signed_file_id,
        "text": order.text,
    }


def case_orders(case_id, *, staff):
    """The case's orders, newest first, of every type (#11.3, view case ``ORD-07``-``ORD-10``).

    Court staff see every order but discarded ones; parties see signed orders only
    (``PUB-02``). A triggered order carries its diary entry as *Business of the Day*
    and, in Gujarat, the signed Roznama's file (``DEN-08``).
    """
    queryset = Order.objects.filter(case_id=case_id).select_related("order_type", "roznama")
    queryset = (
        queryset.exclude(status=OrderStatus.DISCARDED)
        if staff
        else queryset.filter(status__in=(OrderStatus.SIGNED, OrderStatus.TRIGGERED))
    )
    rows = []
    for order in queryset.order_by("-created_at"):
        roznama = getattr(order, "roznama", None)
        rows.append(
            {
                "id": order.pk,
                "type": {"code": order.order_type.code, "label": order.order_type.label},
                "title": order.title,
                "number": order.number,
                "order_date": order.order_date,
                "status": PARTY_STATUS_LABELS[order.status],
                "business_of_the_day": diary.composed_entry(order)
                if order.status == OrderStatus.TRIGGERED
                else "",
                "signed_file_id": order.signed_file_id,
                "roznama_file_id": roznama.signed_file_id
                if roznama and roznama.status == RoznamaStatus.SIGNED
                else "",
            }
        )
    return rows


def diary_entries(court_id, *, date=None, order_type=""):
    """Every triggered order's diary entry together, whatever its type (#6.6, ``DEN-05``).

    Both Roznama-type orders and the Roznamas of normal orders appear, with the
    Roznama's status and number.
    """
    queryset = (
        Order.objects.filter(court_id=court_id, status=OrderStatus.TRIGGERED)
        .select_related("order_type", "roznama")
        .order_by("-triggered_at")
    )
    if date:
        queryset = queryset.filter(Q(hearing__hearing_date=date) | Q(order_date=date))
    if order_type:
        queryset = queryset.filter(order_type__code=order_type)
    orders = list(queryset)
    summaries = get_case_summaries({order.case_id for order in orders})
    hearings = hearing_selectors.get_hearings({o.hearing_id for o in orders if o.hearing_id})
    rows = []
    for order in orders:
        roznama = getattr(order, "roznama", None)
        summary = summaries.get(order.case_id)
        hearing = hearings.get(order.hearing_id)
        rows.append(
            {
                "order_id": order.pk,
                "case": {
                    "id": order.case_id,
                    "display_number": summary.display_number if summary else "",
                    "title": summary.title if summary else "",
                },
                "hearing_date": hearing.hearing_date if hearing else None,
                "hearing_purpose": hearing.purpose_label if hearing else "",
                "entry": diary.composed_entry(order),
                "next_hearing": next_hearing.view(order),
                "type": {"code": order.order_type.code, "label": order.order_type.label},
                "entry_label": order.order_type.diary_entry_label,
                "roznama": {"status": roznama.status, "number": roznama.number}
                if roznama
                else None,
            }
        )
    return rows


def order_status_for_hearings(hearing_ids):
    """Per hearing, ``NONE`` or the order's stages, for the cause list's column (#10.6, ``CLS-07``).

    One order query for a whole day. An order sent for signing with incomplete data
    matches both of its stages (``PND-02``). 0023's ``has_order`` filter should take
    these values.
    """
    hearing_ids = list(hearing_ids)
    result = {
        hearing_id: {"stages": ["NONE"], "order_id": None, "next_hearing": None}
        for hearing_id in hearing_ids
    }
    orders = (
        Order.objects.filter(hearing_id__in=hearing_ids)
        .exclude(status=OrderStatus.DISCARDED)
        .select_related("roznama")
    )
    for order in orders:
        result[order.hearing_id] = {
            "stages": common.stages(order, getattr(order, "roznama", None)),
            "order_id": order.pk,
            "next_hearing": {
                "state": order.next_hearing_state,
                "date": order.next_hearing_date,
                "purpose": order.next_hearing_purpose,
            }
            if order.next_hearing_state != NextHearingState.UNSET
            else None,
        }
    return result


def purpose_labels(codes):
    """``{code: label}`` for hearing purpose codes, one query."""
    return dict(HearingPurpose.objects.filter(code__in=set(codes)).values_list("code", "label"))
