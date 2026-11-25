"""Orders API views (spec 0039 #11).

Views stay thin: each finds who the caller is in the order's courtroom
(``permissions``), validates the shape, hands the action to a service and renders
the result. Mutating text and data take ``If-Match`` against the order's
``text_version`` or ``data_version`` and refuse a stale write with ``412 E14002``.
"""

import re

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.api.schema import error_responses
from apps.cases.models import Case
from apps.esign.views import FORM_METHOD
from apps.hearings import selectors as hearing_selectors

from . import errors, permissions, ports, selectors
from .enums import SHORTCUT_SCOPE_ORDER_TEXT, OrderRole
from .serializers import (
    BulkItemsSerializer,
    BulkNextHearingSerializer,
    BulkResultSerializer,
    BulkTextSerializer,
    CaseOrderSerializer,
    CatalogueItemSerializer,
    CatalogueQuerySerializer,
    ChangesSerializer,
    DiaryEntriesQuerySerializer,
    DiaryEntryRowSerializer,
    DiaryEntrySerializer,
    ItemCreateSerializer,
    ItemValuesSerializer,
    NextHearingInputSerializer,
    NextHearingResultSerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderDocumentSerializer,
    OrderItemSerializer,
    OrdersCourtQuerySerializer,
    OrderTextSerializer,
    OrderTitleSerializer,
    OrderTypeSerializer,
    PendingCountsSerializer,
    PendingQuerySerializer,
    PendingRowSerializer,
    ShortcutQuerySerializer,
    ShortcutSerializer,
    SignConfirmSerializer,
    SignInitiationSerializer,
    SignSerializer,
)
from .services import (
    bulk,
    diary,
    drafting,
    items,
    lifecycle,
    live,
    next_hearing,
    shortcuts,
    signing,
)

UUID_PATTERN = "[0-9a-fA-F-]{36}"
IF_MATCH_RE = re.compile(r'^(?:W/)?"?([td])-(\d+)"?$')

IF_MATCH = OpenApiParameter(
    "If-Match",
    OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=False,
    description='The text version ("t-14") or the order data version ("d-6") you loaded. '
    "A changed order is refused with 412 E14002.",
)

# Errors every action on one order can give.
ACTION_ERRORS = (errors.ROLE_REQUIRED, errors.INVALID_ORDER_ACTION)
STALE_ERRORS = (*ACTION_ERRORS, errors.ORDER_STALE)


def _valid(serializer_class, data, **kwargs):
    serializer = serializer_class(data=data, **kwargs)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def if_match(request, kind):
    """Return the version in ``If-Match`` for ``kind`` (``"t"`` text, ``"d"`` data), or ``None``."""
    raw = request.headers.get("If-Match")
    if not raw:
        return None
    match = IF_MATCH_RE.match(raw.strip())
    if match is None or match.group(1) != kind:
        raise BusinessError(
            api_errors.INVALID, f'If-Match must look like "{kind}-12".', field="If-Match"
        )
    return int(match.group(2))


def _detail(
    order_id, user, *, status_code=status.HTTP_200_OK, serializer=OrderDetailSerializer, **extra
):
    order, roles, staff = permissions.visible_order(user, order_id)
    if not staff:
        return Response(selectors.party_view(order), status=status_code)
    data = {**selectors.order_detail(order, roles), **extra}
    return Response(serializer(data).data, status=status_code)


class OrdersPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class OrdersViewMixin:
    """Reports a service's missing row as ``404``, not a server error."""

    def handle_exception(self, exc):
        if isinstance(exc, ObjectDoesNotExist):
            exc = NotFound(str(exc) or "Not found.")
        return super().handle_exception(exc)


class OrderViewSet(OrdersViewMixin, viewsets.GenericViewSet):
    """One order, its drafting, order data, signing and the bulk actions (#5-#10)."""

    lookup_value_regex = UUID_PATTERN
    pagination_class = OrdersPagination
    serializer_class = OrderDetailSerializer
    list_actions = {"pending"}
    unpaginated_actions = {"pending_counts"}

    # -- create and read -----------------------------------------------------

    @extend_schema(
        request=OrderCreateSerializer,
        responses={
            201: OrderDetailSerializer,
            200: OrderDetailSerializer,
            **error_responses(
                errors.ROLE_REQUIRED,
                errors.CASE_NOT_IN_COURTROOM,
                errors.HEARING_NOT_STARTED,
                errors.ORDER_TYPE_NOT_OFFERED.example(field="order_type"),
                errors.ITEM_NOT_AVAILABLE.example(field="item_type"),
            ),
        },
    )
    def create(self, request):
        """Create a draft: one per hearing, any number per case outside a hearing (#5.1, #5.2).

        A hearing that already has a live order returns it with ``200``, so everyone
        opening the listing works one draft.
        """
        data = _valid(OrderCreateSerializer, request.data)
        if data.get("hearing_id"):
            hearing = hearing_selectors.get_hearing(data["hearing_id"])
            if hearing is None:
                raise NotFound("Hearing not found.")
            permissions.require_role(request.user, hearing.court_id, "create")
            order, created = drafting.create_in_hearing(
                hearing_id=hearing.id, actor=request.user, order_type_code=data.get("order_type")
            )
        else:
            case = Case.objects.filter(pk=data["case_id"]).first()
            if case is None:
                raise NotFound("Case not found.")
            if case.court_id is None:
                raise BusinessError(errors.CASE_NOT_IN_COURTROOM)
            permissions.require_role(request.user, case.court_id, "create")
            order = drafting.create_outside_hearing(
                case_id=case.pk,
                actor=request.user,
                preset=data.get("preset"),
                order_type_code=data.get("order_type"),
            )
            created = True
        return _detail(
            order.pk,
            request.user,
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(responses=error_responses())
    def retrieve(self, request, pk=None):
        """The order screen: text, page, items, next hearing, allowed actions (#10.2).

        Court staff of its courtroom; a party sees a signed order only. Anyone else:
        not found.
        """
        return _detail(pk, request.user)

    # -- drafting ---------------------------------------------------------------

    @extend_schema(
        request=OrderTextSerializer,
        parameters=[IF_MATCH],
        responses={
            200: OrderDetailSerializer,
            **error_responses(
                *STALE_ERRORS,
                errors.ORDER_TEXT_TOO_LARGE.example(field="text"),
                errors.ORDER_TEXT_STRUCTURE_UNSUPPORTED.example(field="text"),
            ),
        },
    )
    @action(detail=True, methods=["patch"])
    def text(self, request, pk=None):
        """Save the order text, as it is typed (#5.4). Same text: no change."""
        order, _ = permissions.actionable_order(request.user, pk, "edit_text")
        data = _valid(OrderTextSerializer, request.data)
        drafting.edit_text(
            order.pk, data["text"], actor=request.user, text_version=if_match(request, "t")
        )
        return _detail(order.pk, request.user)

    @extend_schema(
        request=OrderTitleSerializer,
        responses={200: OrderDetailSerializer, **error_responses(*ACTION_ERRORS)},
    )
    @action(detail=True, methods=["patch"])
    def title(self, request, pk=None):
        """Set the title; it never changes by itself afterwards (#5.5)."""
        order, _ = permissions.actionable_order(request.user, pk, "edit_title")
        drafting.edit_title(
            order.pk, _valid(OrderTitleSerializer, request.data)["title"], actor=request.user
        )
        return _detail(order.pk, request.user)

    @extend_schema(
        request=OrderTypeSerializer,
        responses={
            200: OrderDetailSerializer,
            **error_responses(
                *ACTION_ERRORS,
                errors.ORDER_TYPE_NOT_OFFERED.example(field="order_type"),
                errors.LINKED_DOCUMENTS_WOULD_BE_REMOVED,
            ),
        },
    )
    @action(detail=True, methods=["patch"], url_path="type")
    def order_type(self, request, pk=None):
        """Change the order's type until it is signed (#5.8)."""
        order, _ = permissions.actionable_order(request.user, pk, "change_type")
        data = _valid(OrderTypeSerializer, request.data)
        drafting.change_type(
            order.pk,
            data["order_type"],
            actor=request.user,
            remove_linked_documents=data["remove_linked_documents"],
        )
        return _detail(order.pk, request.user)

    @extend_schema(
        request=OrderDocumentSerializer,
        responses={
            200: OrderDetailSerializer,
            **error_responses(
                *ACTION_ERRORS,
                errors.DOCUMENT_NOT_ON_CASE.example(field="document_id"),
                errors.LINKS_NOT_ALLOWED_FOR_TYPE,
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="documents")
    def documents(self, request, pk=None):
        """Link a document of the case file (#5.6)."""
        order, _ = permissions.actionable_order(request.user, pk, "link_document")
        drafting.link_document(
            order.pk,
            _valid(OrderDocumentSerializer, request.data)["document_id"],
            actor=request.user,
        )
        return _detail(order.pk, request.user)

    @extend_schema(
        request=None, responses={200: OrderDetailSerializer, **error_responses(*ACTION_ERRORS)}
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path=rf"documents/(?P<document_id>{UUID_PATTERN})",
    )
    def unlink_document(self, request, pk=None, document_id=None):
        """Remove a document link (#5.6)."""
        order, _ = permissions.actionable_order(request.user, pk, "link_document")
        drafting.unlink_document(order.pk, document_id, actor=request.user)
        return _detail(order.pk, request.user)

    @extend_schema(
        request=None, responses={200: OrderDetailSerializer, **error_responses(*ACTION_ERRORS)}
    )
    @action(detail=True, methods=["post"])
    def discard(self, request, pk=None):
        """Discard a draft: nothing is recorded on the case (#5.7)."""
        order, _ = permissions.actionable_order(request.user, pk, "discard")
        drafting.discard(order.pk, actor=request.user)
        return _detail(order.pk, request.user)

    # -- order data -----------------------------------------------------------

    @extend_schema(
        request=ItemCreateSerializer,
        parameters=[IF_MATCH],
        responses={
            201: OrderItemSerializer,
            **error_responses(
                *STALE_ERRORS,
                errors.ORDER_DATA_COMPLETE,
                errors.ITEM_NOT_AVAILABLE.example(field="item_type"),
                errors.ITEM_COMBINATION_NOT_ALLOWED.example(field="item_type"),
                errors.ITEM_TARGET_INVALID.example(field="target_id"),
                errors.ITEM_VALUES_INVALID.example(field="values.amount"),
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="items")
    def add_item(self, request, pk=None):
        """Add an order item (#6.2). Defaults are merged under the values given."""
        order, _ = permissions.actionable_order(request.user, pk, "add_item")
        data = _valid(ItemCreateSerializer, request.data)
        item = items.add(
            order.pk,
            data["item_type"],
            target_id=data.get("target_id"),
            values=data.get("values"),
            actor=request.user,
            data_version=if_match(request, "d"),
        )
        order.refresh_from_db()
        problems = items.item_problems(order, item)
        row = {
            "id": item.pk,
            "position": item.position,
            "item_type": {"code": item.item_type.code, "label": item.item_type.label},
            "target_id": item.target_id,
            "values": item.values,
            "source": item.added_by_source,
            "confirmed": item.confirmed,
            "unconfirmed_fields": item.unconfirmed_fields,
            "problems": [
                {"field": p.field, "code": p.code, "message": p.message} for p in problems
            ],
        }
        return Response(OrderItemSerializer(row).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=ItemValuesSerializer,
        parameters=[IF_MATCH],
        responses={
            200: OrderDetailSerializer,
            **error_responses(
                *STALE_ERRORS,
                errors.ORDER_DATA_COMPLETE,
                errors.ITEM_VALUES_INVALID.example(field="values.amount"),
            ),
        },
    )
    @extend_schema(
        methods=["DELETE"],
        request=None,
        parameters=[IF_MATCH],
        responses={
            200: OrderDetailSerializer,
            **error_responses(*STALE_ERRORS, errors.ORDER_DATA_COMPLETE),
        },
    )
    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=rf"items/(?P<item_id>{UUID_PATTERN})",
    )
    def item(self, request, pk=None, item_id=None):
        """Replace an item's values, or remove it and its future workflow (#6.2, ``ITM-09``)."""
        order, _ = permissions.actionable_order(
            request.user, pk, "edit_item" if request.method == "PATCH" else "remove_item"
        )
        version = if_match(request, "d")
        if request.method == "PATCH":
            values = _valid(ItemValuesSerializer, request.data)["values"]
            items.update(order.pk, item_id, values, actor=request.user, data_version=version)
        else:
            items.remove(order.pk, item_id, actor=request.user, data_version=version)
        return _detail(order.pk, request.user)

    @extend_schema(
        request=None, responses={200: OrderDetailSerializer, **error_responses(*ACTION_ERRORS)}
    )
    @action(detail=True, methods=["post"], url_path=rf"items/(?P<item_id>{UUID_PATTERN})/confirm")
    def confirm_item(self, request, pk=None, item_id=None):
        """Confirm an item a reading layer added, and every field of it (#6.2)."""
        order, _ = permissions.actionable_order(request.user, pk, "confirm_item")
        items.confirm(order.pk, item_id, actor=request.user)
        return _detail(order.pk, request.user)

    @extend_schema(
        request=None,
        responses={
            200: OrderDetailSerializer,
            **error_responses(errors.INVALID_ORDER_ACTION, errors.ROLE_REQUIRED),
        },
    )
    @action(
        detail=True,
        methods=["post"],
        url_path=rf"items/(?P<item_id>{UUID_PATTERN})/confirm-paid",
    )
    def confirm_paid(self, request, pk=None, item_id=None):
        """The paying side confirms a witness batta was paid; closes its task (#9.3)."""
        items.confirm_paid(pk, item_id, user=request.user)
        return _detail(pk, request.user)

    @extend_schema(
        request=NextHearingInputSerializer,
        parameters=[IF_MATCH],
        responses={
            200: NextHearingResultSerializer,
            **error_responses(
                *STALE_ERRORS,
                errors.ITEM_VALUES_INVALID.example(field="purpose"),
            ),
        },
    )
    @action(detail=True, methods=["put"], url_path="next-hearing")
    def next_hearing(self, request, pk=None):
        """Set the next hearing: a date and a purpose, or not listed again (#6.4).

        ``apps.hearings`` errors (``E10003``-``E10009``, ``E10014``) pass through
        unchanged; its soft warnings come back in ``warnings``.
        """
        order, _ = permissions.actionable_order(request.user, pk, "set_next_hearing")
        data = _valid(NextHearingInputSerializer, request.data)
        _, warnings = next_hearing.set_next_hearing(
            order.pk,
            state=data["state"],
            date=data.get("date"),
            purpose=data.get("purpose") or None,
            actor=request.user,
            data_version=if_match(request, "d"),
        )
        return _detail(
            order.pk,
            request.user,
            serializer=NextHearingResultSerializer,
            warnings=[{"code": w.code, "message": w.message, "detail": w.detail} for w in warnings],
        )

    @extend_schema(
        request=DiaryEntrySerializer,
        responses={
            200: OrderDetailSerializer,
            **error_responses(
                *ACTION_ERRORS,
                errors.DIARY_ENTRY_LOCKED,
                errors.DIARY_ENTRY_IS_ORDER_TEXT,
                errors.ORDER_TEXT_STRUCTURE_UNSUPPORTED.example(field="text"),
            ),
        },
    )
    @action(detail=True, methods=["put"], url_path="diary-entry")
    def diary_entry(self, request, pk=None):
        """Set the diary entry (#6.6): the order text, or a text of its own."""
        order, _ = permissions.actionable_order(request.user, pk, "edit_diary_entry")
        data = _valid(DiaryEntrySerializer, request.data)
        diary.set_entry(
            order.pk, same_as_text=data["same_as_text"], text=data["text"], actor=request.user
        )
        return _detail(order.pk, request.user)

    @extend_schema(
        request=None,
        responses={
            200: OrderDetailSerializer,
            **error_responses(*ACTION_ERRORS, errors.MANDATORY_FIELDS_MISSING),
        },
    )
    @action(detail=True, methods=["post"], url_path="data/complete")
    def data_complete(self, request, pk=None):
        """Mark the order data complete; a signed order is triggered by it (#6.7)."""
        order, _ = permissions.actionable_order(request.user, pk, "mark_complete")
        lifecycle.mark_complete(order.pk, actor=request.user)
        return _detail(order.pk, request.user)

    @extend_schema(
        request=None,
        responses={
            200: OrderDetailSerializer,
            **error_responses(*ACTION_ERRORS, errors.ORDER_ALREADY_SIGNED),
        },
    )
    @action(detail=True, methods=["post"], url_path="data/reopen")
    def data_reopen(self, request, pk=None):
        """Reopen complete order data, until the order is signed (#6.7)."""
        order, _ = permissions.actionable_order(request.user, pk, "reopen")
        lifecycle.reopen(order.pk, actor=request.user)
        return _detail(order.pk, request.user)

    # -- sending and signing ----------------------------------------------------

    @extend_schema(
        request=None,
        responses={
            200: OrderDetailSerializer,
            **error_responses(
                *ACTION_ERRORS,
                errors.ORDER_TEXT_EMPTY.example(field="text"),
                errors.NEXT_HEARING_NOT_SETTLED,
                errors.ATTENDANCE_INCOMPLETE,
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="send-for-signing")
    def send_for_signing(self, request, pk=None):
        """Send the draft for signing (#7.1): text, next hearing and attendance settled."""
        order, _ = permissions.actionable_order(request.user, pk, "send_for_signing")
        lifecycle.send_for_signing(order.pk, actor=request.user)
        return _detail(order.pk, request.user)

    @extend_schema(
        request=None,
        responses={
            200: OrderDetailSerializer,
            **error_responses(*ACTION_ERRORS, errors.ORDER_ALREADY_SIGNED),
        },
    )
    @action(detail=True, methods=["post"], url_path="move-to-draft")
    def move_to_draft(self, request, pk=None):
        """Move an order sent for signing back to draft (#7.2)."""
        order, _ = permissions.actionable_order(request.user, pk, "move_to_draft")
        lifecycle.move_to_draft(order.pk, actor=request.user)
        return _detail(order.pk, request.user)

    @extend_schema(
        request=SignSerializer,
        responses={
            200: SignInitiationSerializer,
            **error_responses(
                *ACTION_ERRORS, errors.SIGNING_METHOD_NOT_ENABLED.example(field="method")
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="sign")
    def sign(self, request, pk=None):
        """Start Aadhaar e-sign for this order (#8.1); returns the form to post to the ESP."""
        order, _ = permissions.actionable_order(request.user, pk, "sign")
        method = _valid(SignSerializer, request.data)["method"]
        result = signing.start_signing(order.pk, actor=request.user, method=method)
        return Response(_initiation(result))

    @extend_schema(
        request=SignConfirmSerializer,
        responses={
            200: OrderDetailSerializer,
            **error_responses(
                *ACTION_ERRORS, errors.SIGNATURE_NOT_VALID_FOR_ORDER, errors.ORDER_ALREADY_SIGNED
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="sign/confirm")
    def sign_confirm(self, request, pk=None):
        """The browser is back from the ESP: record the signature (#8.1). Idempotent."""
        order, _ = permissions.actionable_order(request.user, pk, "sign")
        signing.record_signature(
            order.pk,
            _valid(SignConfirmSerializer, request.data)["transaction_id"],
            actor=request.user,
        )
        return _detail(order.pk, request.user)

    @extend_schema(
        request=SignSerializer,
        responses={
            200: SignInitiationSerializer,
            **error_responses(*ACTION_ERRORS, errors.DIARY_ENTRY_LOCKED),
        },
    )
    @action(detail=True, methods=["post"], url_path="roznama/sign")
    def roznama_sign(self, request, pk=None):
        """Gujarat: start e-sign of a normal order's Roznama (#8.4)."""
        order, _ = permissions.actionable_order(request.user, pk, "sign_roznama")
        method = _valid(SignSerializer, request.data)["method"]
        result = signing.start_roznama_signing(order.pk, actor=request.user, method=method)
        return Response(_initiation(result))

    @extend_schema(
        request=SignConfirmSerializer,
        responses={
            200: OrderDetailSerializer,
            **error_responses(*ACTION_ERRORS, errors.SIGNATURE_NOT_VALID_FOR_ORDER),
        },
    )
    @action(detail=True, methods=["post"], url_path="roznama/sign/confirm")
    def roznama_sign_confirm(self, request, pk=None):
        """Record the Roznama's signature (#8.4). Triggers nothing."""
        order, _ = permissions.actionable_order(request.user, pk, "sign_roznama")
        signing.record_roznama_signature(
            order.pk,
            _valid(SignConfirmSerializer, request.data)["transaction_id"],
            actor=request.user,
        )
        return _detail(order.pk, request.user)

    # -- live view --------------------------------------------------------------

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "since", OpenApiTypes.STR, description='"<text_version>.<data_version>"'
            )
        ],
        responses={200: ChangesSerializer, 304: None, **error_responses()},
    )
    @action(detail=True, methods=["get"], url_path="changes")
    def changes(self, request, pk=None):
        """Everyone with the draft open polls this (#5.4): ``304`` when nothing changed."""
        order, roles, staff = permissions.visible_order(request.user, pk)
        if not staff:
            raise NotFound("Order not found.")
        etag = live.etag(order)
        if live.unchanged(order, request.query_params.get("since")):
            return Response(status=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        detail = selectors.order_detail(order, roles)
        body = {key: detail[key] for key in ChangesSerializer().fields if key in detail}
        return Response(ChangesSerializer(body).data, headers={"ETag": etag})

    # -- lists and bulk ---------------------------------------------------------

    @extend_schema(
        parameters=[PendingQuerySerializer],
        responses={200: PendingRowSerializer(many=True), **error_responses(errors.ROLE_REQUIRED)},
    )
    @action(detail=False, methods=["get"], url_path="pending")
    def pending(self, request):
        """Pending orders: every order not yet triggered, in four tabs (#10.1).

        Without ``tab`` the list opens on the viewer's own move. The response adds
        the four ``counts`` of the tabs.
        """
        query = _valid(PendingQuerySerializer, request.query_params)
        roles = self._staff_roles(request.user, query["court"])
        tab = query.get("tab") or selectors.default_tab(roles)
        page = self.paginate_queryset(
            selectors.pending_queryset(query["court"], tab, query.get("search", ""))
        )
        rows = PendingRowSerializer(selectors.pending_rows(page, roles, tab), many=True).data
        response = self.get_paginated_response(rows)
        response.data["counts"] = selectors.pending_counts(query["court"])
        response.data["tab"] = tab
        return response

    @extend_schema(
        parameters=[OrdersCourtQuerySerializer],
        responses={200: PendingCountsSerializer, **error_responses(errors.ROLE_REQUIRED)},
    )
    @action(detail=False, methods=["get"], url_path="pending/counts")
    def pending_counts(self, request):
        """The tab counts and the badge: orders at the viewer's own stage (#10.1)."""
        court = _valid(OrdersCourtQuerySerializer, request.query_params)["court"]
        roles = self._staff_roles(request.user, court)
        counts = selectors.pending_counts(court)
        return Response(
            PendingCountsSerializer(
                {"counts": counts, "badge": selectors.badge(roles, counts)}
            ).data
        )

    @staticmethod
    def _staff_roles(user, court_id):
        if not permissions.is_staff(user, court_id):
            raise permissions.role_error("create")
        return permissions.court_roles(user, court_id)

    @extend_schema(
        request=BulkItemsSerializer,
        responses={
            200: BulkResultSerializer,
            **error_responses(errors.ROLE_REQUIRED, errors.BULK_TOO_LARGE),
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk/items")
    def bulk_items(self, request):
        """Add items to several hearing orders of one courtroom (#10.3)."""
        data = _valid(BulkItemsSerializer, request.data)
        result = bulk.bulk_items(
            actor=request.user, order_ids=data["order_ids"], item_specs=data["items"]
        )
        return Response(BulkResultSerializer(result).data)

    @extend_schema(
        request=BulkTextSerializer,
        responses={
            200: BulkResultSerializer,
            **error_responses(
                errors.ROLE_REQUIRED,
                errors.BULK_TOO_LARGE,
                errors.ORDER_TEXT_STRUCTURE_UNSUPPORTED.example(field="text"),
            ),
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk/text")
    def bulk_text(self, request):
        """Append the same text to several listings' drafts (#10.4)."""
        data = _valid(BulkTextSerializer, request.data)
        result = bulk.bulk_text(
            actor=request.user,
            court_id=data["court"],
            hearing_ids=data["hearing_ids"],
            text=data["text"],
        )
        return Response(BulkResultSerializer(result).data)

    @extend_schema(
        request=BulkNextHearingSerializer,
        responses={
            200: BulkResultSerializer,
            **error_responses(errors.ROLE_REQUIRED, errors.BULK_TOO_LARGE),
        },
    )
    @action(detail=False, methods=["post"], url_path="bulk/next-hearing")
    def bulk_next_hearing(self, request):
        """Set the next hearing of several listings from the cause list (#10.5)."""
        data = _valid(BulkNextHearingSerializer, request.data)
        result = bulk.bulk_next_hearing(
            actor=request.user,
            court_id=data["court"],
            hearing_ids=data["hearing_ids"],
            state=data["state"],
            date=data.get("date"),
            purpose=data.get("purpose") or None,
        )
        return Response(BulkResultSerializer(result).data)


def _initiation(result):
    """The e-sign form, as ``apps.esign`` returns it, unchanged (#8.1)."""
    return {
        "transaction_id": str(result.transaction.pk),
        "provider_transaction_id": result.transaction.provider_transaction_id,
        "expires_at": result.transaction.expires_at,
        "esign_url": result.initiation.esign_url,
        "form_method": FORM_METHOD,
        "form_fields": dict(result.initiation.form_fields),
    }


class HearingNextHearingView(OrdersViewMixin, APIView):
    """``PUT /hearings/{hearing_id}/next-hearing/``: the cause list's *Next hearing* column (#10.5)."""

    @extend_schema(
        request=NextHearingInputSerializer,
        parameters=[IF_MATCH],
        responses={
            200: NextHearingResultSerializer,
            **error_responses(errors.ROLE_REQUIRED, errors.HEARING_NOT_STARTED, errors.ORDER_STALE),
        },
    )
    def put(self, request, hearing_id):
        """Write one started listing's order; the same value the order itself edits (``PLC-04``)."""
        hearing = hearing_selectors.get_hearing(hearing_id)
        if hearing is None:
            raise NotFound("Hearing not found.")
        permissions.require_role(request.user, hearing.court_id, "set_next_hearing")
        data = _valid(NextHearingInputSerializer, request.data)
        order, warnings = bulk.set_for_hearing(
            actor=request.user,
            hearing_id=hearing.id,
            state=data["state"],
            date=data.get("date"),
            purpose=data.get("purpose") or None,
            data_version=if_match(request, "d"),
        )
        return _detail(
            order.pk,
            request.user,
            serializer=NextHearingResultSerializer,
            warnings=[{"code": w.code, "message": w.message, "detail": w.detail} for w in warnings],
        )


class OrderItemCatalogueView(OrdersViewMixin, APIView):
    """``GET /order-items/``: the catalogue, and with ``?order=`` its availability for that order (#6.1)."""

    @extend_schema(
        parameters=[CatalogueQuerySerializer],
        responses={200: CatalogueItemSerializer(many=True), **error_responses()},
    )
    def get(self, request):
        query = _valid(CatalogueQuerySerializer, request.query_params)
        order = None
        if query.get("order"):
            order, _, staff = permissions.visible_order(request.user, query["order"])
            if not staff:
                raise NotFound("Order not found.")
        elif not ports.holds_role_anywhere(request.user):
            raise permissions.role_error("create")
        rows = items.catalogue(
            order, search=query.get("search", ""), category=query.get("category", "")
        )
        return Response(CatalogueItemSerializer(rows, many=True).data)


class DiaryEntriesView(OrdersViewMixin, APIView):
    """``GET /diary-entries/``: every triggered order's diary entry together (#6.6, ``DEN-05``)."""

    @extend_schema(
        parameters=[DiaryEntriesQuerySerializer],
        responses={
            200: DiaryEntryRowSerializer(many=True),
            **error_responses(errors.ROLE_REQUIRED),
        },
    )
    def get(self, request):
        query = _valid(DiaryEntriesQuerySerializer, request.query_params)
        if not permissions.is_staff(request.user, query["court"]):
            raise permissions.role_error("create")
        rows = selectors.diary_entries(
            query["court"], date=query.get("date"), order_type=query.get("state_type", "")
        )
        return Response(DiaryEntryRowSerializer(rows, many=True).data)


class CaseOrdersView(OrdersViewMixin, APIView):
    """``GET /cases/{case_id}/orders/``: the case's orders, newest first (#11.3)."""

    @extend_schema(responses={200: CaseOrderSerializer(many=True), **error_responses()})
    def get(self, request, case_id):
        case = Case.objects.filter(pk=case_id).first()
        if case is None:
            raise NotFound("Case not found.")
        staff = bool(case.court_id) and permissions.is_staff(request.user, case.court_id)
        if not staff and not permissions.is_party(request.user, case.pk):
            raise NotFound("Case not found.")
        return Response(
            CaseOrderSerializer(selectors.case_orders(case.pk, staff=staff), many=True).data
        )


class ShortcutViewSet(OrdersViewMixin, viewsets.GenericViewSet):
    """The caller's own shortcuts (#11.2, ``SHC-05``, ``SHC-06``). Nobody else's are ever seen."""

    lookup_value_regex = UUID_PATTERN
    serializer_class = ShortcutSerializer
    unpaginated_actions = {"list"}

    def _require_drafter(self, request):
        """Shortcuts need no role beyond the order drafter's (``SHC-06``)."""
        if not ports.holds_role_anywhere(request.user, OrderRole.ORDER_DRAFTER):
            raise permissions.role_error("create")

    @extend_schema(
        parameters=[ShortcutQuerySerializer],
        responses={200: ShortcutSerializer(many=True), **error_responses(errors.ROLE_REQUIRED)},
    )
    def list(self, request):
        """The caller's shortcuts, optionally on one screen and by name."""
        self._require_drafter(request)
        query = _valid(ShortcutQuerySerializer, request.query_params)
        rows = shortcuts.list_for(
            request.user, scope=query.get("scope", ""), search=query.get("search", "")
        )
        return Response(ShortcutSerializer(rows, many=True).data)

    @extend_schema(
        request=ShortcutSerializer,
        responses={
            201: ShortcutSerializer,
            **error_responses(
                errors.ROLE_REQUIRED,
                errors.SHORTCUT_NAME_TAKEN.example(field="name"),
                errors.ORDER_TEXT_STRUCTURE_UNSUPPORTED.example(field="body"),
            ),
        },
    )
    def create(self, request):
        """Add a shortcut (``SHC-05``). Its scope is the screen it was created on."""
        self._require_drafter(request)
        data = _valid(ShortcutSerializer, request.data)
        row = shortcuts.create(
            request.user,
            name=data["name"],
            body=data["body"],
            scope=data.get("scope") or [SHORTCUT_SCOPE_ORDER_TEXT],
        )
        return Response(ShortcutSerializer(row).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=ShortcutSerializer(partial=True),
        responses={
            200: ShortcutSerializer,
            **error_responses(
                errors.SHORTCUT_NAME_TAKEN.example(field="name"),
                errors.ORDER_TEXT_STRUCTURE_UNSUPPORTED.example(field="body"),
            ),
        },
    )
    def partial_update(self, request, pk=None):
        """Change a shortcut. Only its owner can; for anyone else it does not exist."""
        self._require_drafter(request)
        data = _valid(ShortcutSerializer, request.data, partial=True)
        return Response(ShortcutSerializer(shortcuts.update(request.user, pk, **data)).data)

    @extend_schema(request=None, responses={204: None, **error_responses()})
    def destroy(self, request, pk=None):
        """Remove a shortcut. Only its owner can."""
        self._require_drafter(request)
        shortcuts.delete(request.user, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
