"""PDF API views (spec 0016 #4).

Views validate input, call ``apps.pdf.services.jobs`` and serialize the
result. Mapping, rendering and storage happen in services and workers.

Jobs are visible to the user who requested them; staff see every job.
"""

from django.http import FileResponse, HttpResponse
from django.utils.text import get_valid_filename
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.viewsets import APIModelReadOnlyViewSet

from .exceptions import (
    PDFConfigurationError,
    PDFDependencyError,
    PDFError,
    PDFJobStateError,
    PDFRenderError,
    PDFRequestDataError,
    PDFTemplateNotFound,
)
from .models import PDFJob
from .serializers import (
    PDFDownloadQuerySerializer,
    PDFJobCreateSerializer,
    PDFJobFilterSerializer,
    PDFJobSerializer,
    PDFRenderRequestSerializer,
)
from .services import jobs
from .services.documents import PDFDocumentNotFound, open_document

TAGS = ["pdf"]
CORRELATION_HEADER = "HTTP_X_CORRELATION_ID"


class PDFConflict(APIException):
    """The job is in a state that does not allow the operation."""

    status_code = status.HTTP_409_CONFLICT
    default_code = "conflict"


class PDFUnavailable(APIException):
    """A dependency needed to answer synchronously is unavailable."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_code = "unavailable"


class PDFTimeout(APIException):
    """The synchronous render ran out of time."""

    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    default_code = "timeout"


def to_api_error(exc: PDFError) -> APIException:
    """Translate a service error into a DRF exception with a stable ``code``."""
    detail = {"detail": exc.safe_message, "code": exc.code}
    if isinstance(exc, PDFTemplateNotFound):
        return NotFound(detail)
    if isinstance(exc, PDFRequestDataError | jobs.PDFSyncRenderNotAllowed):
        return ValidationError(detail)
    if isinstance(exc, PDFJobStateError):
        return PDFConflict(detail)
    if isinstance(exc, jobs.PDFSyncRenderTimeout):
        return PDFTimeout(detail)
    if isinstance(exc, PDFDependencyError):
        return PDFUnavailable(detail)
    if isinstance(exc, PDFConfigurationError | PDFRenderError):
        return APIException(detail)
    return APIException(detail)


def _request_meta(request) -> dict:
    return {"correlation_id": request.META.get(CORRELATION_HEADER, "")[:128]}


def _pdf_filename(job: PDFJob, suffix: str = "") -> str:
    name = "-".join(part for part in (job.key, job.entity_id, suffix) if part)
    return f"{get_valid_filename(name) or 'document'}.pdf"


@extend_schema_view(
    list=extend_schema(
        tags=TAGS,
        parameters=[PDFJobFilterSerializer],
        summary="Search PDF jobs by entity, key, tenant or status.",
    ),
    retrieve=extend_schema(tags=TAGS, summary="Retrieve a PDF job; poll until file_ids appear."),
    create=extend_schema(
        tags=TAGS,
        request=PDFJobCreateSerializer,
        responses={202: PDFJobSerializer, 200: PDFJobSerializer},
        summary="Create a generation job (202), or return a reusable one (200, reused=true).",
    ),
    destroy=extend_schema(
        tags=TAGS,
        responses={200: PDFJobSerializer},
        summary="Delete the job's generated documents.",
    ),
    cancel=extend_schema(
        tags=TAGS,
        request=None,
        responses={200: PDFJobSerializer, 409: OpenApiResponse(description="Job is terminal.")},
        summary="Cancel a job that has not finished.",
    ),
    download=extend_schema(
        tags=TAGS,
        parameters=[
            OpenApiParameter("sequence", int, description="Bulk chunk sequence to download."),
            OpenApiParameter("index", int, description="Index into file_ids (default 0)."),
        ],
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
        summary="Download a generated document.",
    ),
)
class PDFJobViewSet(APIModelReadOnlyViewSet):
    """Create, search, retrieve, cancel, download and delete PDF jobs."""

    authentication_classes = [SessionAuthentication, TokenAuthentication]
    serializer_class = PDFJobSerializer
    lookup_field = "id"

    def get_queryset(self):
        """Return the caller's jobs (all jobs for staff), filtered on list."""
        queryset = PDFJob.objects.select_related("template_version")
        if getattr(self, "swagger_fake_view", False):
            # Schema generation has no real user; the model is all it needs.
            return queryset.none()
        user = self.request.user
        if not (user.is_staff or user.is_superuser):
            queryset = queryset.filter(requested_by=user)
        if self.action == "list":
            filters = PDFJobFilterSerializer(data=self.request.query_params)
            filters.is_valid(raise_exception=True)
            queryset = queryset.filter(**filters.validated_data)
        return queryset

    def get_serializer_context(self):
        """Include chunk detail on single-job responses."""
        context = super().get_serializer_context()
        context["include_records"] = self.action != "list"
        return context

    def _respond(self, job, *, reused=False, status_code=status.HTTP_200_OK):
        context = {**self.get_serializer_context(), "reused": reused}
        return Response(PDFJobSerializer(job, context=context).data, status=status_code)

    def create(self, request, *args, **kwargs):
        """Validate, then create/enqueue a job or return the reusable one."""
        serializer = PDFJobCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        organization = params.get("organization_id")
        try:
            job, reused = jobs.create_job(
                jobs.JobRequest(
                    key=params["key"],
                    tenant_id=params["tenant_id"],
                    data=params["data"],
                    entity_id=params["entity_id"],
                    organization_id=organization.pk if organization else None,
                    locale=params["locale"],
                    force_regenerate=params["force_regenerate"],
                    **_request_meta(request),
                ),
                user=request.user,
            )
        except PDFError as exc:
            raise to_api_error(exc) from exc
        return self._respond(
            job,
            reused=reused,
            status_code=status.HTTP_200_OK if reused else status.HTTP_202_ACCEPTED,
        )

    def destroy(self, request, *args, **kwargs):
        """Delete the job's documents through the File Storage Service."""
        job = self.get_object()
        if not job.is_terminal:
            raise PDFConflict(
                {
                    "detail": "Cancel the job before deleting its documents.",
                    "code": "PDF_JOB_ACTIVE",
                }
            )
        try:
            job = jobs.delete_job_documents(job)
        except PDFError as exc:
            raise to_api_error(exc) from exc
        return self._respond(job)

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        """Cancel a ``CREATED``/``QUEUED``/``PROCESSING`` job; terminal jobs conflict."""
        job = self.get_object()
        try:
            job = jobs.cancel_job(job.pk)
        except PDFError as exc:
            raise to_api_error(exc) from exc
        return self._respond(job)

    @action(detail=True, methods=["get"])
    def download(self, request, *args, **kwargs):
        """Stream a document obtained from the File Storage Service."""
        job = self.get_object()
        query = PDFDownloadQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)

        suffix = ""
        if "sequence" in query.validated_data:
            sequence = query.validated_data["sequence"]
            record = job.records.filter(sequence=sequence).exclude(file_id="").first()
            if record is None:
                raise NotFound({"detail": "No document for that chunk.", "code": "PDF_NO_DOCUMENT"})
            file_id, suffix = record.file_id, f"part-{sequence + 1}"
        else:
            index = query.validated_data.get("index", 0)
            if index >= len(job.file_ids or []):
                raise NotFound(
                    {"detail": "The job has no such document.", "code": "PDF_NO_DOCUMENT"}
                )
            file_id = job.file_ids[index]
            if len(job.file_ids) > 1:
                suffix = f"part-{index + 1}"

        try:
            handle = open_document(file_id)
        except PDFDocumentNotFound as exc:
            raise NotFound(
                {"detail": "The document no longer exists.", "code": "PDF_NO_DOCUMENT"}
            ) from exc
        return FileResponse(
            handle,
            as_attachment=True,
            filename=_pdf_filename(job, suffix),
            content_type="application/pdf",
        )


class PDFRenderView(APIView):
    """Synchronous render: returns PDF bytes, stores nothing, creates no job."""

    authentication_classes = [SessionAuthentication, TokenAuthentication]

    @extend_schema(
        tags=TAGS,
        request=PDFRenderRequestSerializer,
        responses={
            (200, "application/pdf"): OpenApiTypes.BINARY,
            400: OpenApiResponse(
                description="Invalid request or template not renderable synchronously."
            ),
            404: OpenApiResponse(description="Unknown template key."),
            504: OpenApiResponse(description="Render exceeded PDF_SYNC_RENDER_TIMEOUT_SECONDS."),
        },
        summary="Render a small document synchronously.",
    )
    def post(self, request):
        """Render and return ``application/pdf`` bytes."""
        serializer = PDFRenderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data
        try:
            content = jobs.render_sync(
                params["key"],
                params["tenant_id"],
                params["data"],
                locale=params["locale"],
                user=request.user,
                **_request_meta(request),
            )
        except PDFError as exc:
            raise to_api_error(exc) from exc
        response = HttpResponse(content, content_type="application/pdf")
        filename = get_valid_filename(params["key"]) or "document"
        response["Content-Disposition"] = f'inline; filename="{filename}.pdf"'
        return response
