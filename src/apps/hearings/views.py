"""Hearings API views (spec 0023 #10).

Views stay thin: each checks who the caller is in the hearing's court
(``permissions``), hands the action to a service or the read to
``queries``, and renders the result. There is no create, update or delete of
a hearing: dates come from orders (in-process, ``services.listing``) and
court-side moves.

Start, pass over, end, reschedule and cancel take ``If-Unmodified-Since``
against the hearing's ``updated_at`` and refuse a stale write with
``412 E10002``.
"""

import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils.http import parse_http_date_safe
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.api.schema import error_responses
from apps.cases.selectors import get_listability
from apps.organizations.models import Organization

from . import conf, errors, permissions, queries
from .models import BulkRescheduleJob, HearingPurpose
from .serializers import (
    AttendanceInputSerializer,
    BoardQuerySerializer,
    BulkActionResultSerializer,
    BulkActionSerializer,
    BulkConfirmedSerializer,
    BulkJobSerializer,
    BulkPreviewResultSerializer,
    BulkPreviewSerializer,
    BusinessDateSerializer,
    CalendarDaySerializer,
    CalendarEntryCreateSerializer,
    CalendarEntrySerializer,
    CalendarQuerySerializer,
    CountsSerializer,
    CourtQuerySerializer,
    EndSerializer,
    HearingDetailSerializer,
    HearingMovedSerializer,
    HearingSerializer,
    NextHearingSerializer,
    PurposeSerializer,
    QueueItemSerializer,
    ReorderSerializer,
    RescheduleSerializer,
)
from .services import calendar, courtroom, listing, reschedule

UUID_PATTERN = "[0-9a-fA-F-]{36}"
CALENDAR_DEFAULT_DAYS = 30

IF_UNMODIFIED_SINCE = OpenApiParameter(
    "If-Unmodified-Since",
    OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=False,
    description="An HTTP date. A hearing changed after it is refused with 412 E10002.",
)
IF_NONE_MATCH = OpenApiParameter(
    "If-None-Match",
    OpenApiTypes.STR,
    location=OpenApiParameter.HEADER,
    required=False,
    description="The ETag of the last response; an unchanged board returns 304 with no body.",
)

# Errors every action on one hearing can give.
ACTION_ERRORS = (errors.NOT_COURT_STAFF, errors.ROLE_REQUIRED, errors.INVALID_TRANSITION)
STALE_ERRORS = (*ACTION_ERRORS, errors.HEARING_STALE)
DATE_ERRORS = (
    errors.DATE_IN_PAST.example(field="hearing_date"),
    errors.DATE_NOT_SITTING.example(field="hearing_date"),
    errors.DATE_BEYOND_HORIZON.example(field="hearing_date"),
)


def _valid(serializer_class, data, **kwargs):
    serializer = serializer_class(data=data, **kwargs)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def if_unmodified_since(request):
    """Return the ``If-Unmodified-Since`` header as an aware datetime, or None."""
    raw = request.headers.get("If-Unmodified-Since")
    if not raw:
        return None
    seconds = parse_http_date_safe(raw)
    if seconds is None:
        raise BusinessError(
            api_errors.INVALID,
            "If-Unmodified-Since must be an HTTP date, e.g. Thu, 12 Nov 2026 05:40:00 GMT.",
        )
    return datetime.datetime.fromtimestamp(seconds, tz=datetime.UTC)


def _etag_matches(request, etag):
    header = request.headers.get("If-None-Match", "")
    tags = {tag.strip().removeprefix("W/") for tag in header.split(",")}
    return etag in tags or "*" in tags


def _court(court_id):
    return get_object_or_404(Organization, pk=court_id)


class HearingPagination(PageNumberPagination):
    """Page-number pagination with ``page_size`` up to 100 (#10.3).

    A single court's board for one date may ask for up to
    ``board_max_hearings``, so the cause list loads a whole day at once
    (``CLS-13``).
    """

    page_size_query_param = "page_size"
    max_page_size = 100


class HearingsViewMixin:
    """Reports a service's missing row as ``404``, not a server error."""

    def handle_exception(self, exc):
        if isinstance(exc, ObjectDoesNotExist):
            exc = NotFound(str(exc) or "Not found.")
        return super().handle_exception(exc)


class HearingViewSet(HearingsViewMixin, viewsets.GenericViewSet):
    """The board, one hearing, and running the courtroom (#5, #6, #8.2, #10)."""

    lookup_value_regex = UUID_PATTERN
    pagination_class = HearingPagination
    list_actions = {"scheduling_queue"}
    unpaginated_actions = {"current", "reorder"}

    SERIALIZERS = {
        "retrieve": HearingDetailSerializer,
        "attendance": HearingDetailSerializer,
        "reschedule": HearingMovedSerializer,
        "counts": CountsSerializer,
        "scheduling_queue": QueueItemSerializer,
        "bulk_action": BulkActionResultSerializer,
    }

    def get_serializer_class(self):
        return self.SERIALIZERS.get(self.action, HearingSerializer)

    def _hearing(self, hearing, roles, serializer_class=HearingSerializer, **extra):
        return Response(serializer_class({**queries.hearing_view(hearing, roles), **extra}).data)

    @extend_schema(
        parameters=[BoardQuerySerializer],
        responses=error_responses(errors.NOT_COURT_STAFF),
    )
    def list(self, request):
        """The cause list and search: one court's hearings, by status then serial number (#10.3).

        Defaults to today's board. One court and one date may be fetched whole,
        up to ``board_max_hearings`` per page.
        """
        query = _valid(BoardQuerySerializer, request.query_params)
        roles = permissions.require_staff(request.user, query["court"])
        if queries.is_one_day(query):
            self.paginator.max_page_size = conf.board_max_hearings()
        page = self.paginate_queryset(queries.board(query["court"], query))
        return self.get_paginated_response(
            HearingSerializer(queries.hearing_views(page, roles=roles), many=True).data
        )

    def retrieve(self, request, pk=None):
        """One hearing with its attendance, date changes and the hearings before and after.

        Court staff of its court, or a party of its case (never a provisional
        or released hearing). Anyone else: not found.
        """
        hearing, roles = permissions.visible_hearing(request.user, pk)
        return Response(HearingDetailSerializer(queries.hearing_detail(hearing, roles)).data)

    def _act(self, request, pk, action_name, service, **kwargs):
        hearing, roles = permissions.actionable_hearing(request.user, pk, action_name)
        hearing = service(
            hearing_id=hearing.pk,
            actor=request.user,
            court_id=hearing.court_id,
            if_unmodified_since=if_unmodified_since(request),
            **kwargs,
        )
        return self._hearing(hearing, roles)

    @extend_schema(
        request=None,
        parameters=[IF_UNMODIFIED_SINCE],
        responses=error_responses(*STALE_ERRORS, errors.HEARING_NOT_TODAY),
    )
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        """Call the hearing: in progress (#6.1). Only on the day it is listed for."""
        return self._act(request, pk, "start", courtroom.start)

    @extend_schema(
        request=None, parameters=[IF_UNMODIFIED_SINCE], responses=error_responses(*STALE_ERRORS)
    )
    @action(detail=True, methods=["post"], url_path="pass-over")
    def pass_over(self, request, pk=None):
        """Set the hearing aside unheard, to return to later today (#6.2)."""
        return self._act(request, pk, "pass_over", courtroom.pass_over)

    @extend_schema(
        request=EndSerializer,
        parameters=[IF_UNMODIFIED_SINCE],
        responses=error_responses(*STALE_ERRORS),
    )
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        """End the hearing (#6.3). Needs no order; records who sought an adjournment, if anyone."""
        data = _valid(EndSerializer, request.data)
        return self._act(
            request,
            pk,
            "end",
            courtroom.end,
            adjournment_sought_by=data["adjournment_sought_by"],
        )

    @extend_schema(
        request=RescheduleSerializer,
        parameters=[IF_UNMODIFIED_SINCE],
        responses=error_responses(
            *STALE_ERRORS,
            *DATE_ERRORS,
            errors.REASON_NEEDS_ORDER.example(field="reason_code"),
            errors.NOTHING_TO_CHANGE.example(field="hearing_date"),
            errors.PURPOSE_INACTIVE.example(field="purpose"),
            errors.CASE_ALREADY_SCHEDULED,
            errors.COURT_DAY_FULL.example(field="hearing_date"),
        ),
    )
    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        """Move the hearing for a court-side reason, without an order (#8.2).

        A full day (warn mode) and a party at the adjournment limit come back
        in ``warnings``.
        """
        hearing, roles = permissions.actionable_hearing(request.user, pk, "reschedule")
        data = _valid(RescheduleSerializer, request.data)
        result = reschedule.reschedule(
            hearing_id=hearing.pk,
            hearing_date=data["hearing_date"],
            purpose_code=data.get("purpose"),
            reason_code=data["reason_code"],
            reason_text=data["reason_text"],
            actor=request.user,
            court_id=hearing.court_id,
            if_unmodified_since=if_unmodified_since(request),
        )
        return self._hearing(
            result.hearing, roles, HearingMovedSerializer, warnings=result.warnings
        )

    @extend_schema(
        request=None, parameters=[IF_UNMODIFIED_SINCE], responses=error_responses(*STALE_ERRORS)
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """Cancel a hearing listed in error (#7.6). Every other cancellation comes from an order."""
        return self._act(request, pk, "cancel", listing.cancel_listed_in_error)

    @extend_schema(
        request=AttendanceInputSerializer,
        responses=error_responses(
            errors.NOT_COURT_STAFF,
            errors.ROLE_REQUIRED,
            errors.ATTENDANCE_LOCKED,
            errors.NOT_ON_ROLL.example(field="marks[0]"),
        ),
    )
    @action(detail=True, methods=["put"])
    def attendance(self, request, pk=None):
        """Replace the hearing's attendance roll (#6.5); anyone left out is unmarked."""
        hearing, roles = permissions.actionable_hearing(request.user, pk, "mark_attendance")
        data = _valid(AttendanceInputSerializer, request.data)
        courtroom.set_attendance(hearing_id=hearing.pk, marks=data["marks"], actor=request.user)
        hearing.refresh_from_db()
        return Response(HearingDetailSerializer(queries.hearing_detail(hearing, roles)).data)

    @extend_schema(
        parameters=[CourtQuerySerializer, IF_NONE_MATCH],
        responses={
            200: HearingSerializer(many=True),
            304: None,
            **error_responses(errors.NOT_COURT_STAFF),
        },
    )
    @action(detail=False, methods=["get"])
    def current(self, request):
        """The court's hearings in progress today, by serial number (#6.4, ``HRG-10``).

        Poll with ``If-None-Match``: an unchanged board returns ``304``.
        """
        court_id = _valid(CourtQuerySerializer, request.query_params)["court"]
        roles = permissions.require_staff(request.user, court_id)
        etag = courtroom.board_etag(court_id)
        if _etag_matches(request, etag):
            return Response(status=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
        views = queries.hearing_views(courtroom.current(court_id), roles=roles)
        return Response(HearingSerializer(views, many=True).data, headers={"ETag": etag})

    @extend_schema(
        parameters=[CourtQuerySerializer], responses=error_responses(errors.NOT_COURT_STAFF)
    )
    @action(detail=False, methods=["get"])
    def counts(self, request):
        """Badge counts: today's board by status, not reached, the queue, stale holds (#10.4.4)."""
        court_id = _valid(CourtQuerySerializer, request.query_params)["court"]
        permissions.require_staff(request.user, court_id)
        return Response(CountsSerializer(queries.counts(court_id)).data)

    @extend_schema(
        parameters=[CourtQuerySerializer], responses=error_responses(errors.NOT_COURT_STAFF)
    )
    @action(detail=False, methods=["get"], url_path="scheduling-queue")
    def scheduling_queue(self, request):
        """Registered cases of the court with no live hearing, longest waiting first (#10.4.8)."""
        court_id = _valid(CourtQuerySerializer, request.query_params)["court"]
        permissions.require_staff(request.user, court_id)
        page = self.paginate_queryset(queries.scheduling_queue(court_id))
        return self.get_paginated_response(QueueItemSerializer(page, many=True).data)

    @extend_schema(
        request=BulkActionSerializer,
        responses=error_responses(errors.NOT_COURT_STAFF, errors.ROLE_REQUIRED),
    )
    @action(detail=False, methods=["post"], url_path="bulk-action")
    def bulk_action(self, request):
        """End or pass over several hearings in one press (#6.6).

        Ending a scheduled hearing starts and ends it at once. A hearing that
        cannot take the action is left as it is, under ``skipped``.
        """
        data = _valid(BulkActionSerializer, request.data)
        roles = permissions.require_action(request.user, data["court"], "bulk_action")
        result = courtroom.bulk_action(
            court_id=data["court"],
            hearing_ids=data["hearing_ids"],
            action=data["action"],
            actor=request.user,
        )
        # Offer only what the caller's roles allow, as every hearing response does (#10.2).
        for skipped in result.skipped:
            skipped["allowed_actions"] = permissions.allowed_for_roles(
                skipped["allowed_actions"], roles
            )
        return Response(BulkActionResultSerializer(result).data)

    @extend_schema(
        request=ReorderSerializer,
        responses=error_responses(
            errors.NOT_COURT_STAFF,
            errors.ROLE_REQUIRED,
            errors.BOARD_MISMATCH.example(field="hearing_ids"),
        ),
    )
    @action(detail=False, methods=["post"], url_path="board/reorder")
    def reorder(self, request):
        """Put the day's waiting hearings in a new order; returns that day's board (#5)."""
        data = _valid(ReorderSerializer, request.data)
        roles = permissions.require_action(request.user, data["court"], "reorder")
        courtroom.reorder_board(
            court_id=data["court"],
            hearing_date=data["hearing_date"],
            hearing_ids=data["hearing_ids"],
            actor=request.user,
        )
        board = courtroom.board(data["court"], data["hearing_date"])
        return Response(
            HearingSerializer(queries.hearing_views(board, roles=roles), many=True).data
        )


class BulkRescheduleViewSet(HearingsViewMixin, viewsets.GenericViewSet):
    """Court-side moves of many hearings: preview, confirm, follow (#8.3)."""

    lookup_value_regex = UUID_PATTERN
    serializer_class = BulkJobSerializer

    def _job(self, user, pk):
        """The job, for court staff of its court; anyone else is told it does not exist."""
        job = get_object_or_404(BulkRescheduleJob.objects.select_related("court"), pk=pk)
        roles = permissions.court_roles(user, job.court_id)
        if not roles:
            raise NotFound("Bulk move not found.")
        return job, roles

    @extend_schema(
        request=BulkPreviewSerializer,
        responses={
            200: BulkPreviewResultSerializer,
            **error_responses(
                errors.NOT_COURT_STAFF,
                errors.ROLE_REQUIRED,
                errors.REASON_NEEDS_ORDER.example(field="reason_code"),
                errors.BULK_TOO_LARGE.example(field="hearing_ids"),
                errors.INVALID_TRANSITION.example(field="hearing_ids"),
                errors.NOTHING_TO_CHANGE.example(field="hearing_ids"),
                errors.DATE_NOT_SITTING.example(field="target_date"),
            ),
        },
    )
    @action(detail=False, methods=["post"])
    def preview(self, request):
        """Plan the move and store it as a preview; nothing else changes (#8.3)."""
        data = _valid(BulkPreviewSerializer, request.data)
        permissions.require_action(request.user, data["court"], "bulk_reschedule")
        preview = reschedule.preview_bulk(
            court_id=data["court"],
            hearing_ids=data["hearing_ids"],
            mode=data["mode"],
            target_date=data.get("target_date"),
            schedule_after=data.get("schedule_after"),
            block_source_dates=data["block_source_dates"],
            reason_code=data["reason_code"],
            reason_text=data["reason_text"],
            actor=request.user,
        )
        return Response(BulkPreviewResultSerializer(preview).data)

    @extend_schema(
        request=None,
        responses={
            202: BulkConfirmedSerializer,
            **error_responses(
                errors.ROLE_REQUIRED, errors.PREVIEW_EXPIRED, errors.PREVIEW_ALREADY_CONFIRMED
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """Confirm the preview; the move runs in the background (#8.3). Poll the job for progress."""
        job, roles = self._job(request.user, pk)
        permissions.require_role(roles, "bulk_reschedule")
        job = reschedule.confirm_bulk(job_id=job.pk, actor=request.user)
        return Response(BulkConfirmedSerializer(job).data, status=status.HTTP_202_ACCEPTED)

    def retrieve(self, request, pk=None):
        """The bulk move and what became of each hearing in it (#8.3)."""
        job, _roles = self._job(request.user, pk)
        return Response(BulkJobSerializer(job).data)


class HearingPurposeViewSet(viewsets.GenericViewSet):
    """Active hearing purposes, in dropdown order (#10.4.5)."""

    serializer_class = PurposeSerializer
    pagination_class = None
    queryset = HearingPurpose.objects.active().order_by("sequence", "code")

    def list(self, request):
        """Every active purpose; a retired one cannot be chosen for a new date."""
        return Response(PurposeSerializer(self.get_queryset(), many=True).data)


class CourtHearingsViewSet(HearingsViewMixin, viewsets.GenericViewSet):
    """A court's calendar, calendar entries and business date (#9)."""

    lookup_field = "court_id"
    lookup_value_regex = UUID_PATTERN
    serializer_class = CalendarDaySerializer
    pagination_class = None
    unpaginated_actions = {"calendar"}

    SERIALIZERS = {"business_date": BusinessDateSerializer, "entries": CalendarEntrySerializer}

    def get_serializer_class(self):
        return self.SERIALIZERS.get(self.action, CalendarDaySerializer)

    @extend_schema(
        parameters=[CalendarQuerySerializer],
        responses=error_responses(errors.NOT_COURT_STAFF),
    )
    @action(detail=True, methods=["get"])
    def calendar(self, request, court_id=None):
        """The date picker: each day's sitting, capacity and load, split by purpose (#9.1).

        ``from`` defaults to today and ``to`` to 30 days on; at most 92 days.
        """
        _court(court_id)
        permissions.require_staff(request.user, court_id)
        query = _valid(CalendarQuerySerializer, request.query_params)
        date_from = query.get("from") or calendar.business_date()
        date_to = query.get("to") or date_from + datetime.timedelta(days=CALENDAR_DEFAULT_DAYS - 1)
        days = calendar.calendar(court_id, date_from, date_to)
        return Response(CalendarDaySerializer(days, many=True).data)

    @extend_schema(
        request=CalendarEntryCreateSerializer,
        responses={
            201: CalendarEntrySerializer,
            **error_responses(
                errors.NOT_COURT_STAFF,
                errors.ROLE_REQUIRED,
                errors.DATE_IN_PAST.example(field="date"),
                errors.DATE_HAS_HEARINGS.example(field="date"),
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="calendar/entries")
    def entries(self, request, court_id=None):
        """Mark a day non-sitting or a reduced sitting (#9.2).

        Refused on a past date, and as a non-sitting day while hearings are
        listed or held on it: move them first.
        """
        _court(court_id)
        permissions.require_action(request.user, court_id, "calendar_entry")
        data = _valid(CalendarEntryCreateSerializer, request.data)
        entry = calendar.create_entry(
            court_id=court_id,
            date=data["date"],
            entry_type=data["entry_type"],
            reason=data["reason"],
            capacity_override=data.get("capacity_override"),
            actor=request.user,
        )
        return Response(CalendarEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=None,
        responses=error_responses(
            errors.NOT_COURT_STAFF, errors.ROLE_REQUIRED, errors.DATE_IN_PAST.example(field="date")
        ),
    )
    @action(
        detail=True,
        methods=["delete"],
        url_path=rf"calendar/entries/(?P<entry_id>{UUID_PATTERN})",
        url_name="calendar-entry",
    )
    def delete_entry(self, request, court_id=None, entry_id=None):
        """Remove a calendar entry; the day sits again and nothing moves back (#9.2)."""
        _court(court_id)
        permissions.require_action(request.user, court_id, "calendar_entry")
        calendar.delete_entry(court_id=court_id, entry_id=entry_id, actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="business-date")
    def business_date(self, request, court_id=None):
        """The court's today, whether it sits today, and the time parties report (#9.3)."""
        _court(court_id)
        return Response(BusinessDateSerializer(calendar.business_date_info(court_id)).data)


class CaseHearingsViewSet(HearingsViewMixin, viewsets.GenericViewSet):
    """One case's hearings, for court staff of its court and its parties (#10.4.2, #10.4.3)."""

    serializer_class = HearingSerializer
    pagination_class = HearingPagination

    def get_serializer_class(self):
        return NextHearingSerializer if self.action == "next" else HearingSerializer

    def _roles(self, request, case_id):
        listability = get_listability(case_id)
        return permissions.case_access(request.user, case_id, listability.court_id)

    def list(self, request, case_id=None):
        """The case's hearings, newest first (``HRG-01``); parties never see provisional ones."""
        roles = self._roles(request, case_id)
        page = self.paginate_queryset(queries.case_hearings(case_id, roles))
        return self.get_paginated_response(
            HearingSerializer(queries.hearing_views(page, roles=roles), many=True).data
        )

    @action(detail=False, methods=["get"])
    def next(self, request, case_id=None):
        """The next hearing tile: in progress, else scheduled, else null (``OVW-01``-``OVW-04``)."""
        roles = self._roles(request, case_id)
        hearing = queries.case_next_hearing(case_id)
        view = queries.hearing_view(hearing, roles) if hearing else None
        return Response(NextHearingSerializer({"hearing": view}).data)
