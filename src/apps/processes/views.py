"""Processes API views (spec 0028 #11).

Views stay thin: each checks who may read (``permissions``), hands a step to
its service, which checks the step's action, and renders the result. There
is no create: processes come from orders (``services.issue``).
"""

import uuid

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from apps.api.schema import error_responses
from apps.cases.selectors import get_case_summaries
from apps.hearings.selectors import hearing_dates

from . import conf, errors, permissions, selectors
from .models import NonDeliveryReason, ProcessType
from .serializers import (
    CourtQuerySerializer,
    ListQuerySerializer,
    NonDeliveryReasonSerializer,
    OutcomeSerializer,
    ProcessCountsSerializer,
    ProcessDetailSerializer,
    ProcessRegisterEntrySerializer,
    ProcessSerializer,
    ProcessTypeSerializer,
    RecallResultSerializer,
    RecallSerializer,
    SendSerializer,
)
from .services import dispatch, steps

UUID_PATTERN = "[0-9a-fA-F-]{36}"
# Errors every step on one process can give.
STEP_ERRORS = (errors.PROCESS_ACTION_NOT_ALLOWED, errors.INVALID_PROCESS_ACTION)


def _valid(serializer_class, data):
    serializer = serializer_class(data=data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def response_context(user, processes):
    """What ``ProcessSerializer`` reads, fetched once for every process in the response."""
    return {
        "user": user,
        "cases": get_case_summaries({process.case_id for process in processes}),
        "hearing_dates": hearing_dates(
            {process.hearing_id for process in processes if process.hearing_id}
        ),
    }


class ProcessPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 100


class ProcessesViewMixin:
    """Reports a service's missing row as ``404``, not a server error."""

    def handle_exception(self, exc):
        if isinstance(exc, ObjectDoesNotExist):
            exc = NotFound("Process not found.")
        return super().handle_exception(exc)


class ProcessViewSet(ProcessesViewMixin, viewsets.GenericViewSet):
    """A courtroom's processes and the court-side steps on them (#11.1, #11.2)."""

    lookup_value_regex = UUID_PATTERN
    pagination_class = ProcessPagination
    SERIALIZERS = {
        "retrieve": ProcessDetailSerializer,
        "counts": ProcessCountsSerializer,
        "recall": RecallResultSerializer,
    }

    def get_serializer_class(self):
        return self.SERIALIZERS.get(self.action, ProcessSerializer)

    def _render(self, processes, serializer_class=ProcessSerializer, many=True):
        rows = processes if many else [processes]
        context = response_context(self.request.user, rows)
        return serializer_class(processes, many=many, context=context).data

    def _one(self, process_id, serializer_class=ProcessSerializer):
        process = permissions.visible_process(self.request.user, process_id)
        return Response(self._render(process, serializer_class, many=False))

    @extend_schema(parameters=[ListQuerySerializer])
    def list(self, request):
        """One courtroom's processes, filtered and sorted (#11.2)."""
        query = _valid(ListQuerySerializer, request.query_params)
        permissions.require_court_reader(request.user, query["court"])
        page = self.paginate_queryset(selectors.court_processes(request.user, query))
        return self.get_paginated_response(self._render(page))

    def retrieve(self, request, pk=None):
        """One process with its history. Court staff of its courtroom, or a party of its case."""
        return self._one(pk, ProcessDetailSerializer)

    @extend_schema(parameters=[CourtQuerySerializer])
    @action(detail=False, methods=["get"])
    def counts(self, request):
        """Counts per status and channel, and of the caller's moves, for a screen's tabs."""
        court_id = _valid(CourtQuerySerializer, request.query_params)["court"]
        permissions.require_court_reader(request.user, court_id)
        return Response(ProcessCountsSerializer(selectors.counts(request.user, court_id)).data)

    @extend_schema(
        request=None,
        responses=error_responses(*STEP_ERRORS, errors.NO_ENVELOPE_FOR_CHANNEL),
    )
    @action(detail=True, methods=["post"])
    def envelope(self, request, pk=None):
        """Record receipt of the process's envelope at the counter (#7.1, ``STP-02``)."""
        permissions.visible_process(request.user, pk)
        steps.receive_envelope(process_id=pk, actor=request.user)
        return self._one(pk)

    @extend_schema(
        request=SendSerializer,
        responses=error_responses(
            *STEP_ERRORS,
            errors.INVALID_PROCESS_ACTION.example(
                "Only a proclamation by hand is marked as published.", field="published"
            ),
        ),
    )
    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        """Mark a signed process sent on a manual channel; a proclamation by hand, published (#8.1)."""
        data = _valid(SendSerializer, request.data)
        permissions.visible_process(request.user, pk)
        dispatch.send(process_id=pk, actor=request.user, published=data["published"])
        return self._one(pk)

    @extend_schema(
        request=OutcomeSerializer,
        responses=error_responses(
            *STEP_ERRORS,
            errors.OUTCOME_RECORDED_BY_SYSTEM,
            errors.REASON_REQUIRED.example(field="reason"),
            errors.OUTCOME_DATE_INVALID.example(field="outcome_date"),
        ),
    )
    @action(detail=True, methods=["post"])
    def outcome(self, request, pk=None):
        """Record what became of a sent process on a manual status channel (#8.2)."""
        data = _valid(OutcomeSerializer, request.data)
        permissions.visible_process(request.user, pk)
        dispatch.record_outcome(process_id=pk, actor=request.user, **data)
        return self._one(pk)

    @extend_schema(
        request=RecallSerializer,
        responses=error_responses(
            errors.PROCESS_ACTION_NOT_ALLOWED, errors.BULK_TOO_LARGE.example(field="process_ids")
        ),
    )
    @action(detail=False, methods=["post"])
    def recall(self, request):
        """Recall processes with no outcome yet; those already ended come back as skipped (#8.4)."""
        data = _valid(RecallSerializer, request.data)
        dispatch.check_bulk_size(data["process_ids"])
        permissions.visible_processes(request.user, data["process_ids"])
        recalled, skipped = dispatch.recall(
            process_ids=data["process_ids"], actor=request.user, comment=data["comment"]
        )
        context = response_context(request.user, [*recalled, *skipped])
        return Response(
            RecallResultSerializer({"recalled": recalled, "skipped": skipped}, context=context).data
        )


class CaseProcessesViewSet(ProcessesViewMixin, viewsets.GenericViewSet):
    """The case's process register (#11.3, ``view-case.md`` §7)."""

    serializer_class = ProcessRegisterEntrySerializer
    unpaginated_actions = {"list"}

    def list(self, request, case_id=None):
        """The case's processes by person, then by round, newest first. Empty before any issue."""
        case_id = uuid.UUID(case_id)
        permissions.require_case_reader(request.user, case_id)
        register = selectors.case_register(case_id)
        processes = [
            process
            for entry in register
            for group in entry["groups"]
            for process in group["processes"]
        ]
        context = response_context(request.user, processes)
        return Response(ProcessRegisterEntrySerializer(register, many=True, context=context).data)


class ProcessTypeViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Active process types with the channels this deployment offers for each (#11.4)."""

    serializer_class = ProcessTypeSerializer
    pagination_class = None
    queryset = ProcessType.objects.active().prefetch_related("type_channels__channel")


class NonDeliveryReasonViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The state's reasons for a negative outcome (``DSP-09``)."""

    serializer_class = NonDeliveryReasonSerializer
    pagination_class = None

    def get_queryset(self):
        return NonDeliveryReason.objects.active().filter(state_code=conf.state_code())
