"""Applications API views (spec 0033 #15).

Views stay thin: they check shape, hand the action to a service or the read to
``selectors`` and render the result. Every court act is an order (``ALC-22``):
nothing here changes an application on the court's behalf. Filer writes take
``If-Match: <version>`` and refuse a stale one with ``412 E13026``.
"""

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api import errors as api_errors
from apps.api.errors import BusinessError
from apps.api.schema import error_responses
from apps.esign import errors as esign_errors
from apps.esign.views import initiation_payload
from apps.files.services import FileNotFound, get_file, get_file_content
from apps.pdf import errors as pdf_errors

from . import access, errors, selectors
from .serializers import (
    ApplicationCreateSerializer,
    ApplicationDetailSerializer,
    ApplicationRowSerializer,
    ApplicationTypeSerializer,
    ApplicationTypesSerializer,
    ApplicationWriteSerializer,
    CaseListQuerySerializer,
    CourtListQuerySerializer,
    CourtQuerySerializer,
    CourtQueueQuerySerializer,
    DocumentSerializer,
    DocumentUploadSerializer,
    ESignStartSerializer,
    FilerSerializer,
    FormContextSerializer,
    NeedsAttentionSerializer,
    PreviewSerializer,
    ProceedToSignSerializer,
    QueueCountsSerializer,
    QueueRowSerializer,
    SignConfirmSerializer,
    SignSerializer,
    SignUploadSerializer,
)
from .services import drafting, objections, signing
from .services.calendar import today

UUID_PATTERN = "[0-9a-fA-F-]{36}"

IF_MATCH = OpenApiParameter(
    "If-Match",
    OpenApiTypes.INT,
    location=OpenApiParameter.HEADER,
    required=False,
    description="The detail's `version`; a stale one is refused with 412 E13026.",
)

FILER_ERRORS = (errors.ACTION_NOT_ALLOWED, errors.CANNOT_DRAFT, errors.APPLICATION_STALE)
SIGN_ERRORS = (
    errors.ACTION_NOT_ALLOWED,
    errors.NOT_THE_SIGNER,
    errors.SIGNING_METHOD_NOT_ENABLED.example(field="method"),
    errors.HEARING_NOT_UPCOMING,
    errors.TARGET_NOT_PENDING,
)


def _valid(serializer_class, data, **kwargs):
    serializer = serializer_class(data=data, **kwargs)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def expected_version(request):
    """The ``If-Match`` version, or None; ETag quoting (``"9"``, ``W/"9"``) is accepted."""
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip().removeprefix("W/").strip('"'))
    except ValueError as exc:
        raise BusinessError(errors.APPLICATION_STALE) from exc


def _detail_response(application, user, *, code=status.HTTP_200_OK, extra=None):
    data = selectors.detail(application, user)
    if extra:
        data = {**extra, "application": data}
    return Response(data, status=code, headers={"ETag": f'"{application.version}"'})


def _stream(content, filename):
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


class PreviewFormatNegotiation(DefaultContentNegotiation):
    """``?format=pdf`` on the preview (#6.5a) is this module's, not DRF's renderer override."""

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class ApplicationPagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 100


class CaseApplicationsViewSet(viewsets.GenericViewSet):
    """``/cases/{case_id}/applications/`` and ``/cases/{case_id}/application-types/`` (#15.1)."""

    serializer_class = ApplicationRowSerializer
    pagination_class = ApplicationPagination
    unpaginated_actions = {"filers"}

    @extend_schema(
        operation_id="case_applications_list",
        parameters=[CaseListQuerySerializer],
        responses=ApplicationRowSerializer(many=True),
    )
    def list(self, request, case_id=None):
        """The case's applications the caller may see (#14.1)."""
        filters = _valid(CaseListQuerySerializer, request.query_params)
        queryset = selectors.case_list(case_id, request.user, filters=filters)
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(selectors.list_rows(page, request.user))

    @extend_schema(
        operation_id="case_applications_create",
        request=ApplicationCreateSerializer,
        responses={
            201: ApplicationDetailSerializer,
            200: ApplicationDetailSerializer,
            **error_responses(
                errors.CASE_NOT_ON_FILE,
                errors.CANNOT_DRAFT,
                errors.TYPE_NOT_AVAILABLE.example(field="application_type"),
                errors.RAISED_BY_INVALID.example(field="raised_by"),
                errors.LITIGANT_INVALID.example(field="litigant"),
                errors.FIELD_NOT_FOR_TYPE.example(field="data.sureties"),
                errors.DOCUMENT_NOT_ON_APPLICATION,
                errors.OBJECTION_NOT_ALLOWED,
                errors.OBJECTION_TAKEN,
                errors.TARGET_NOT_PENDING,
                errors.LITIGANT_NOT_EDITABLE.example(field="data.participant_id"),
                errors.PHONE_IN_USE.example(field="data.details.phone_number"),
            ),
        },
    )
    def create(self, request, case_id=None):
        """Start a draft (#6.3); an objection through here is the same as ``/objection/``."""
        data = _valid(ApplicationCreateSerializer, request.data)
        application, created = drafting.create(case_id, request.user, data)
        return _detail_response(
            application, request.user, code=status.HTTP_201_CREATED if created else 200
        )

    @extend_schema(operation_id="case_applications_filers", responses=FilerSerializer(many=True))
    @action(detail=False, methods=["get"])
    def filers(self, request, case_id=None):
        """The people who raised a visible application on the case (#14.1)."""
        return Response(FilerSerializer(selectors.filers(case_id, request.user), many=True).data)

    @extend_schema(
        operation_id="case_applications_needs_attention",
        responses=NeedsAttentionSerializer,
    )
    @action(detail=False, methods=["get"], url_path="needs-attention")
    def needs_attention(self, request, case_id=None):
        """What still needs a step from the caller, grouped (#14.2)."""
        return Response({"groups": selectors.needs_attention(case_id, request.user)})


class ApplicationTypesView(APIView):
    """``GET /cases/{case_id}/application-types/`` (#6.1)."""

    @extend_schema(operation_id="case_application_types", responses=ApplicationTypesSerializer)
    def get(self, request, case_id):
        can_raise, offered = drafting.available_types(case_id, request.user)
        types = []
        for row, suggested in offered:
            item = ApplicationTypeSerializer(row).data
            item["suggested"] = suggested
            types.append(item)
        types.sort(key=lambda t: not t["suggested"])
        return Response({"can_raise": can_raise, "types": types})


class ApplicationFormView(APIView):
    """``GET /cases/{case_id}/application-types/{code}/form/`` (#6.2)."""

    @extend_schema(
        operation_id="case_application_form",
        responses={
            200: FormContextSerializer,
            **error_responses(
                errors.CASE_NOT_ON_FILE,
                errors.CANNOT_DRAFT,
                errors.TYPE_NOT_AVAILABLE.example(field="application_type"),
            ),
        },
    )
    def get(self, request, case_id, code):
        context = drafting.form_context(case_id, code, request.user)
        return Response(
            {
                **context,
                "type": ApplicationTypeSerializer(context["type"]).data,
            }
        )


class ApplicationViewSet(viewsets.GenericViewSet):
    """``/applications/…`` (#15.1, #15.2)."""

    content_negotiation_class = PreviewFormatNegotiation
    serializer_class = ApplicationDetailSerializer
    lookup_value_regex = UUID_PATTERN
    pagination_class = ApplicationPagination
    list_actions = {"court_queue"}

    def get_parsers(self):
        if getattr(self, "action", None) in ("documents", "sign_upload"):
            return [MultiPartParser(), FormParser()]
        return [JSONParser(), MultiPartParser(), FormParser()]

    # Reads ------------------------------------------------------------------------

    @extend_schema(operation_id="applications_retrieve")
    def retrieve(self, request, pk=None):
        """The application, for anyone who can see it (#14.3, #14.4)."""
        application = access.get_visible(pk, request.user)
        return _detail_response(application, request.user)

    @extend_schema(
        operation_id="applications_court_list",
        parameters=[CourtListQuerySerializer],
        responses=QueueRowSerializer(many=True),
    )
    def list(self, request):
        """Submitted applications across a courtroom's cases, for its staff (#14.4)."""
        query = _valid(CourtListQuerySerializer, request.query_params)
        queryset = selectors.court_queryset(request.user, query["court"]).order_by("-submitted_at")
        if query.get("status"):
            queryset = queryset.filter(status=query["status"])
        if query.get("type"):
            queryset = queryset.filter(application_type__code=query["type"])
        if query.get("decision_date_before"):
            queryset = queryset.filter(decision_date__lt=query["decision_date_before"])
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(selectors.queue_rows(page, today(), {}))

    @extend_schema(
        operation_id="applications_court_queue",
        parameters=[CourtQueueQuerySerializer],
        responses=QueueRowSerializer(many=True),
    )
    @action(detail=False, methods=["get"], url_path="court-queue")
    def court_queue(self, request):
        """The court's Applications screen: views, type-cut queues, facets (#14.5)."""
        query = _valid(CourtQueueQuerySerializer, request.query_params)
        rows, facets, day, live = selectors.court_queue(
            request.user,
            query["court"],
            view=query.get("view"),
            queue=query.get("queue"),
            filters=query,
        )
        page = self.paginate_queryset(rows)
        response = self.get_paginated_response(
            selectors.queue_rows(page, day, live, queue=query.get("queue"))
        )
        response.data["today"] = day
        response.data["facets"] = facets
        return response

    @extend_schema(
        operation_id="applications_court_queue_counts",
        parameters=[CourtQuerySerializer],
        responses=QueueCountsSerializer,
    )
    @action(detail=False, methods=["get"], url_path="court-queue/counts")
    def court_queue_counts(self, request):
        """Counts per view and per queue; only onboard and decide are badged (#14.5)."""
        query = _valid(CourtQuerySerializer, request.query_params)
        return Response(selectors.court_counts(request.user, query["court"]))

    # Drafting ---------------------------------------------------------------------

    @extend_schema(
        operation_id="applications_update",
        request=ApplicationWriteSerializer,
        parameters=[IF_MATCH],
        responses=error_responses(
            *FILER_ERRORS,
            errors.RAISED_BY_INVALID.example(field="raised_by"),
            errors.LITIGANT_INVALID.example(field="litigant"),
            errors.FIELD_NOT_FOR_TYPE.example(field="data.sureties"),
            errors.DOCUMENT_NOT_ON_APPLICATION,
        ),
    )
    def partial_update(self, request, pk=None):
        """Edit a draft (#6.3); the type is fixed once created."""
        access.get_visible(pk, request.user)
        data = _valid(ApplicationWriteSerializer, request.data)
        application = drafting.update(pk, request.user, data, version=expected_version(request))
        return _detail_response(application, request.user)

    @extend_schema(
        operation_id="applications_delete",
        parameters=[IF_MATCH],
        responses={204: None, **error_responses(*FILER_ERRORS, errors.PAYMENT_IN_FLIGHT)},
    )
    def destroy(self, request, pk=None):
        """Delete before submission (#6.5b, ``ALC-39``)."""
        access.get_visible(pk, request.user)
        drafting.delete(pk, request.user, version=expected_version(request))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        operation_id="applications_documents_add",
        request={"multipart/form-data": DocumentUploadSerializer},
        parameters=[IF_MATCH],
        responses={
            201: DocumentSerializer,
            **error_responses(
                *FILER_ERRORS,
                errors.DOCUMENT_NOT_ACCEPTED.example(field="file"),
                errors.DOCUMENT_NOT_ON_APPLICATION.example(field="field_path"),
                api_errors.REQUIRED.example(field="name"),
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def documents(self, request, pk=None):
        """Attach a supporting document, or a file to a type field (#6.4)."""
        access.get_visible(pk, request.user)
        data = _valid(DocumentUploadSerializer, request.data)
        document = drafting.add_document(
            pk,
            request.user,
            data["file"],
            name=data.get("name", ""),
            field_path=data.get("field_path", ""),
            version=expected_version(request),
        )
        return Response(DocumentSerializer(document).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="applications_proceed_to_sign",
        request=None,
        parameters=[IF_MATCH],
        responses={
            200: ProceedToSignSerializer,
            **error_responses(
                *FILER_ERRORS,
                errors.APPLICATION_INCOMPLETE.example(field="raised_by"),
                errors.DETAILS_REQUIRED.example(field="details"),
                errors.HEARING_NOT_UPCOMING,
                errors.TARGET_NOT_PENDING,
                pdf_errors.NO_DOCUMENT,
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="proceed-to-sign")
    def proceed_to_sign(self, request, pk=None):
        """Check completeness, render the copy to sign, open *Sign application* (#6.5)."""
        access.get_visible(pk, request.user)
        application = drafting.proceed_to_sign(pk, request.user, version=expected_version(request))
        waiting_on = (
            selectors._user_name(application.raised_by)
            if application.raised_by_id != request.user.pk
            else None
        )
        return _detail_response(application, request.user, extra={"waiting_on": waiting_on})

    @extend_schema(
        operation_id="applications_back_to_draft",
        request=None,
        parameters=[IF_MATCH],
        responses=error_responses(*FILER_ERRORS),
    )
    @action(detail=True, methods=["post"], url_path="back-to-draft")
    def back_to_draft(self, request, pk=None):
        """Pending Signature back to Draft, everything kept (#6.6, ``ALC-31``)."""
        access.get_visible(pk, request.user)
        application = drafting.back_to_draft(pk, request.user, version=expected_version(request))
        return _detail_response(application, request.user)

    @extend_schema(
        operation_id="applications_preview",
        parameters=[
            OpenApiParameter(
                "format",
                OpenApiTypes.STR,
                enum=["json", "pdf"],
                required=False,
                description="`pdf` returns the render as a PDF (the stored copy once pending signature).",
            )
        ],
        responses={200: PreviewSerializer},
    )
    @action(detail=True, methods=["get"])
    def preview(self, request, pk=None):
        """The application laid out as the court's template, before signing (#6.5a)."""
        if request.query_params.get("format") == "pdf":
            application, content = drafting.preview_pdf(pk, request.user)
            return _stream(content, f"application-{application.pk}.pdf")
        _, structure = drafting.preview(pk, request.user)
        return Response(PreviewSerializer(structure).data)

    # Signing ----------------------------------------------------------------------

    @extend_schema(
        operation_id="applications_sign",
        request=SignSerializer,
        responses={
            201: ESignStartSerializer,
            **error_responses(
                *SIGN_ERRORS, esign_errors.ALREADY_IN_PROGRESS, esign_errors.DISABLED
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def sign(self, request, pk=None):
        """Start Aadhaar e-sign on the copy to sign (#6.7)."""
        access.get_visible(pk, request.user)
        data = _valid(SignSerializer, request.data)
        result = signing.initiate(
            pk,
            request.user,
            method=data["method"],
            sign_placeholder=data.get("sign_placeholder"),
        )
        return Response(initiation_payload(result), status=status.HTTP_201_CREATED)

    @extend_schema(
        operation_id="applications_sign_confirm",
        request=SignConfirmSerializer,
        responses=error_responses(*SIGN_ERRORS, errors.SIGNATURE_NOT_VALID),
    )
    @action(detail=True, methods=["post"], url_path="sign/confirm")
    def sign_confirm(self, request, pk=None):
        """Record a successful e-sign; idempotent on the transaction (#6.7)."""
        access.get_visible(pk, request.user)
        data = _valid(SignConfirmSerializer, request.data)
        application = signing.confirm(pk, request.user, transaction_id=data["transaction_id"])
        return _detail_response(application, request.user)

    @extend_schema(
        operation_id="applications_sign_upload",
        request={"multipart/form-data": SignUploadSerializer},
        responses=error_responses(*SIGN_ERRORS, errors.DOCUMENT_NOT_ACCEPTED.example(field="file")),
    )
    @action(detail=True, methods=["post"], url_path="sign/upload")
    def sign_upload(self, request, pk=None):
        """Upload a physically signed copy, where the state enables it (#6.7)."""
        access.get_visible(pk, request.user)
        data = _valid(SignUploadSerializer, request.data)
        application = signing.upload_signed_copy(pk, request.user, data["file"])
        return _detail_response(application, request.user)

    # Objection --------------------------------------------------------------------

    @extend_schema(
        operation_id="applications_objection",
        request=None,
        responses={
            201: ApplicationDetailSerializer,
            200: ApplicationDetailSerializer,
            **error_responses(
                errors.OBJECTION_NOT_ALLOWED,
                errors.OBJECTION_TAKEN,
                errors.TARGET_NOT_PENDING,
                errors.CASE_NOT_ON_FILE,
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def objection(self, request, pk=None):
        """Start an objection to this application, or return the caller's own draft (#9)."""
        objection, created = objections.start_objection(pk, request.user)
        return _detail_response(
            objection, request.user, code=status.HTTP_201_CREATED if created else 200
        )


class ApplicationDocumentView(APIView):
    """``GET`` / ``DELETE /applications/{id}/documents/{doc_id}/`` (#6.4)."""

    @extend_schema(
        operation_id="applications_document_download",
        responses={(200, "application/octet-stream"): OpenApiResponse(OpenApiTypes.BINARY)},
    )
    def get(self, request, pk, document_id):
        """Download a file of an application the caller may see.

        ``signed`` as ``document_id`` is the signed application itself.
        """
        application = access.get_visible(pk, request.user)
        if str(document_id) == "signed":
            file_id = application.signed_file_id
        else:
            document = application.documents.filter(pk=document_id).first()
            file_id = document.file_id if document else ""
        if not file_id:
            raise NotFound("Document not found.")
        try:
            meta = get_file(file_id)
            with get_file_content(file_id) as handle:
                content = handle.read()
        except FileNotFound as exc:
            raise NotFound("Document not found.") from exc
        response = HttpResponse(content, content_type=meta.get("content_type") or "application/pdf")
        response["Content-Disposition"] = f'inline; filename="{meta.get("file_name", "document")}"'
        return response

    @extend_schema(
        operation_id="applications_document_delete",
        parameters=[IF_MATCH],
        responses={204: None, **error_responses(*FILER_ERRORS, errors.DOCUMENT_IN_USE)},
    )
    def delete(self, request, pk, document_id):
        access.get_visible(pk, request.user)
        drafting.remove_document(pk, document_id, request.user, version=expected_version(request))
        return Response(status=status.HTTP_204_NO_CONTENT)
