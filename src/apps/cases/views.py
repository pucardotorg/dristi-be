"""Case filing API views (spec 0021 §2, §3, §5).

Ids in POST/PUT paths may be a case id or a draft session id; the first save
on a draft creates the case (see ``services.get_or_create_case``). Other case
routes take a case id; a document or evidence item is changed by its own id
(``/case-documents/{id}``, ``/case-evidence/{id}``). Callers only ever reach
their own cases.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api import errors as api_errors
from apps.api.schema import error_responses

from . import errors
from .models import NOT_JOINABLE_STATUSES, Case, CaseDocument, CaseEvidence, CaseStatus
from .serializers import (
    CaseDocumentSerializer,
    CaseDocumentUploadSerializer,
    CaseEvidenceSerializer,
    CaseSerializer,
    CaseTypeDescriptionSerializer,
    DetailsSectionSerializer,
    DraftSessionSerializer,
    EvidenceCreateSerializer,
    EvidenceUpdateSerializer,
)
from .services import case_types, services

TAGS = ["cases"]


@extend_schema(tags=TAGS)
class CaseTypeListView(APIView):
    """GET /case-types — every case type and what it accepts."""

    @extend_schema(
        tags=TAGS,
        # Explicit: the default collides with the detail route's.
        operation_id="v1_case_types_list",
        responses={200: CaseTypeDescriptionSerializer(many=True)},
    )
    def get(self, request):
        """Return each case type's sections, document types and evidence schemas."""
        return Response(
            [case_types.get_description(case_type) for case_type in case_types.CASE_TYPES]
        )


@extend_schema(tags=TAGS)
class CaseTypeDetailView(APIView):
    """GET /case-types/{case_type} — what one case type accepts."""

    @extend_schema(tags=TAGS, responses={200: CaseTypeDescriptionSerializer})
    def get(self, request, case_type):
        """Return the case type's sections, document types and evidence schemas."""
        if case_type not in case_types.CASE_TYPES:
            raise NotFound("Unknown case type.")
        return Response(case_types.get_description(case_type))


# Filters are GET-only, so they are attached to ``get`` rather than the class.
@extend_schema_view(
    get=extend_schema(
        tags=TAGS,
        parameters=[
            OpenApiParameter("status", str, description="Comma-separated statuses."),
            OpenApiParameter("created_by", str, enum=["me"]),
        ],
    )
)
class CaseListView(generics.ListAPIView):
    """GET /cases — the caller's cases. POST /cases — start a draft session."""

    serializer_class = CaseSerializer

    def get_queryset(self):
        """Return the caller's cases, optionally filtered by status."""
        params = self.request.query_params
        if params.get("created_by") not in (None, "me"):
            raise api_errors.INVALID_CHOICE.validation_error(
                {"created_by": ["Only 'me' is supported."]}
            )

        queryset = Case.objects.filter(created_by=self.request.user)
        if params.get("status"):
            statuses = params["status"].split(",")
            unknown = sorted(set(statuses) - set(CaseStatus.values))
            if unknown:
                raise api_errors.INVALID_CHOICE.validation_error(
                    {"status": [f"Unknown status: {', '.join(unknown)}."]}
                )
            queryset = queryset.filter(status__in=statuses)
        return queryset

    @extend_schema(
        tags=TAGS, request=DraftSessionSerializer, responses={201: DraftSessionSerializer}
    )
    def post(self, request):
        """Start a draft session. No case is created until data is first saved."""
        serializer = DraftSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = services.start_draft(request.user, **serializer.validated_data)
        return Response(DraftSessionSerializer(draft).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS)
class CaseByNumberView(generics.RetrieveAPIView):
    """GET /cases/by-number/{case_number} — find a registered case to join.

    Open to any registered user, so it returns metadata only; cases that are
    not yet registered are not found.
    """

    serializer_class = CaseSerializer
    lookup_field = "case_number"
    queryset = Case.objects.exclude(status__in=NOT_JOINABLE_STATUSES)


@extend_schema_view(
    get=extend_schema(tags=TAGS, parameters=[OpenApiParameter("document_type", str)])
)
class CaseDocumentListView(generics.ListAPIView):
    """GET /cases/{case_id}/documents — active documents. POST — upload one."""

    serializer_class = CaseDocumentSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        """Return the case's active documents, optionally of one type."""
        case = services.get_case(self.kwargs["case_id"], self.request.user)
        queryset = CaseDocument.objects.active().filter(case=case).select_related("document")
        if self.request.query_params.get("document_type"):
            queryset = queryset.filter(document_type=self.request.query_params["document_type"])
        return queryset

    @extend_schema(
        tags=TAGS,
        request=CaseDocumentUploadSerializer,
        responses={
            201: CaseDocumentSerializer,
            **error_responses(
                errors.NOT_ACCEPTED_FOR_CASE_TYPE.example(field="document_type"),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def post(self, request, case_id):
        """Upload a case document; the first save on a draft creates the case."""
        serializer = CaseDocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        document = services.add_document(case_id, request.user, data["file"], data["document_type"])
        return Response(CaseDocumentSerializer(document).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS)
class CaseDocumentDetailView(APIView):
    """DELETE /case-documents/{case_document_id} — soft delete."""

    @extend_schema(tags=TAGS, responses={204: None, **error_responses(errors.CASE_NOT_EDITABLE)})
    def delete(self, request, case_document_id):
        """Remove a document from its case."""
        services.remove_document(case_document_id, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=TAGS)
class CaseDetailsView(APIView):
    """GET /cases/{case_id}/details — every details section."""

    # One key per section of the case's type, so the shape varies by case type;
    # GET /case-types/{case_type} lists the sections and their schemas.
    @extend_schema(tags=TAGS, responses={200: OpenApiTypes.OBJECT})
    def get(self, request, case_id):
        """Return the case's details, one key per section."""
        return Response(services.get_details(case_id, request.user))


@extend_schema(tags=TAGS)
class CaseDetailsSectionView(APIView):
    """PUT /cases/{case_id}/details/{section} — replace one section."""

    @extend_schema(
        tags=TAGS,
        # The body is the section object; its schema depends on the case type and
        # section, and is served by GET /case-types/{case_type}.
        request=OpenApiTypes.OBJECT,
        responses={
            200: DetailsSectionSerializer,
            **error_responses(
                errors.NOT_ACCEPTED_FOR_CASE_TYPE.example(field="section"),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def put(self, request, case_id, section):
        """Replace a section; the first save on a draft creates the case."""
        if not isinstance(request.data, dict):
            raise api_errors.INCORRECT_TYPE.validation_error({"data": ["Expected a JSON object."]})
        case = services.save_details_section(case_id, request.user, section, request.data)
        return Response({"case_id": case.id, "section": section, "data": request.data})


@extend_schema_view(
    get=extend_schema(tags=TAGS, parameters=[OpenApiParameter("evidence_type", str)])
)
class CaseEvidenceListView(generics.ListAPIView):
    """GET /cases/{case_id}/evidence — active evidence. POST — add evidence."""

    serializer_class = CaseEvidenceSerializer

    def get_queryset(self):
        """Return the case's active evidence, optionally of one type."""
        case = services.get_case(self.kwargs["case_id"], self.request.user)
        queryset = (
            CaseEvidence.objects.active().filter(case=case).order_by("evidence_type", "ordinal")
        )
        if self.request.query_params.get("evidence_type"):
            queryset = queryset.filter(evidence_type=self.request.query_params["evidence_type"])
        return queryset

    @extend_schema(
        tags=TAGS,
        request=EvidenceCreateSerializer,
        responses={
            201: CaseEvidenceSerializer,
            **error_responses(
                errors.NOT_ACCEPTED_FOR_CASE_TYPE.example(field="evidence_type"),
                errors.DOCUMENT_NOT_ON_CASE.example(field="case_document_id"),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def post(self, request, case_id):
        """Add evidence; the first save on a draft creates the case."""
        serializer = EvidenceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        evidence = services.add_evidence(case_id, request.user, **serializer.validated_data)
        return Response(CaseEvidenceSerializer(evidence).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=TAGS)
class CaseEvidenceDetailView(APIView):
    """PATCH or DELETE /case-evidence/{case_evidence_id}."""

    @extend_schema(
        tags=TAGS,
        request=EvidenceUpdateSerializer,
        responses={
            200: CaseEvidenceSerializer,
            **error_responses(
                errors.DOCUMENT_NOT_ON_CASE.example(field="case_document_id"),
                errors.CASE_NOT_EDITABLE,
            ),
        },
    )
    def patch(self, request, case_evidence_id):
        """Replace ``evidence_info`` and/or link or unlink a document."""
        evidence = services.get_evidence(case_evidence_id, request.user)
        serializer = EvidenceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        evidence = services.update_evidence(evidence, request.user, **serializer.validated_data)
        return Response(CaseEvidenceSerializer(evidence).data)

    @extend_schema(tags=TAGS, responses={204: None, **error_responses(errors.CASE_NOT_EDITABLE)})
    def delete(self, request, case_evidence_id):
        """Remove evidence from its case."""
        evidence = services.get_evidence(case_evidence_id, request.user)
        services.remove_evidence(evidence, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
